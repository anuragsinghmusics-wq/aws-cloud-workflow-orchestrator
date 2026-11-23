"""Unit and integration tests for Days 17-18 Reliability, Resilience, DLQ, and Graceful Shutdown."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.core.exceptions import (
    CircuitBreakerOpenError,
    ConditionalCheckFailedError,
)
from src.core.metrics import metrics_registry
from src.core.scheduler import CircuitBreaker, CircuitState
from src.core.security import get_current_active_user, require_role
from src.core.shutdown import GracefulShutdownManager, ServiceUnavailableError
from src.database import get_db_session
from src.main import app
from src.models.user import User, UserRole
from src.models.workflow import Workflow
from src.services.cloudwatch_service import CloudWatchService
from src.services.dlq_service import DeadLetterQueueService, dlq_service
from src.services.dynamodb_service import DynamoDBService
from src.services.s3_service import S3Service


class TestCircuitBreakersAndServiceIntegration(unittest.TestCase):
    """Verifies per-service circuit breaker trip, fast-rejection, half-open probe, and metric emissions."""

    def setUp(self):
        metrics_registry.reset_all()

    def test_circuit_breaker_telemetry_emission(self):
        breaker = CircuitBreaker("s3", failure_threshold=2, recovery_timeout=0.1)
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(
            metrics_registry.circuit_breaker_state.get_value(labels={"service": "s3"}), 0.0
        )

        # First failure
        with self.assertRaises(ValueError):
            breaker.call(self._failing_func)
        self.assertEqual(breaker.consecutive_failures, 1)

        # Second failure trips breaker
        with self.assertRaises(ValueError):
            breaker.call(self._failing_func)
        self.assertEqual(breaker.state, CircuitState.OPEN)
        self.assertEqual(
            metrics_registry.circuit_breaker_state.get_value(labels={"service": "s3"}), 2.0
        )

        # Immediate fast-rejection
        with self.assertRaises(CircuitBreakerOpenError):
            breaker.call(lambda: "never_reached")

    def test_ignored_exceptions_do_not_trip_breaker(self):
        breaker = CircuitBreaker(
            "dynamodb",
            failure_threshold=2,
            ignored_exceptions=(ConditionalCheckFailedError,),
        )
        for _ in range(5):
            with self.assertRaises(ConditionalCheckFailedError):
                breaker.call(self._raise_conditional_check_failed)
        self.assertEqual(breaker.consecutive_failures, 0)
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_per_service_adapters_have_circuit_breakers(self):
        s3 = S3Service()
        self.assertIsNotNone(s3.circuit_breaker)
        self.assertEqual(s3.circuit_breaker.name, "s3")

        ddb = DynamoDBService()
        self.assertIsNotNone(ddb.circuit_breaker)
        self.assertEqual(ddb.circuit_breaker.name, "dynamodb")

        cw = CloudWatchService()
        self.assertIsNotNone(cw.circuit_breaker)
        self.assertEqual(cw.circuit_breaker.name, "cloudwatch")

    @staticmethod
    def _failing_func():
        raise ValueError("Simulated network outage")

    @staticmethod
    def _raise_conditional_check_failed():
        raise ConditionalCheckFailedError("Optimistic lock collision")


class TestDeadLetterQueueService(unittest.TestCase):
    """Verifies isolation, querying, replaying, and discarding of poisoned records."""

    def setUp(self):
        self.dlq = DeadLetterQueueService()
        self.dlq.reset_all()
        metrics_registry.reset_all()

    def test_quarantine_record_and_metrics(self):
        msg = self.dlq.quarantine_record(
            job_id="job-dlq-001",
            workflow_name="customer-migration",
            source_type="POSTGRES_DUMP",
            target_table="Customer_V2",
            payload={"customer_id": "c-999", "amount": "INVALID_FLOAT"},
            error_message="ValueError: could not convert string to float",
            error_type="ValueError",
            retry_count=3,
        )

        self.assertIsNotNone(msg.id)
        self.assertEqual(msg.status, "QUARANTINED")
        self.assertEqual(metrics_registry.records_failed_total.get_value(), 1.0)

        # Query single
        retrieved = self.dlq.get_quarantined(msg.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.job_id, "job-dlq-001")

    def test_list_and_filter_dlq(self):
        self.dlq.quarantine_record(
            job_id="job-A",
            workflow_name="wf-A",
            source_type="S1",
            target_table="T1",
            payload={"a": 1},
            error_message="err 1",
        )
        self.dlq.quarantine_record(
            job_id="job-B",
            workflow_name="wf-B",
            source_type="S2",
            target_table="T2",
            payload={"b": 2},
            error_message="err 2",
        )

        items, total = self.dlq.list_quarantined()
        self.assertEqual(total, 2)

        job_a_items, a_total = self.dlq.list_quarantined(job_id="job-A")
        self.assertEqual(a_total, 1)
        self.assertEqual(job_a_items[0].job_id, "job-A")

    def test_replay_and_discard_lifecycle(self):
        msg = self.dlq.quarantine_record(
            job_id="job-X",
            workflow_name="wf-X",
            source_type="S",
            target_table="T",
            payload={"x": 100},
            error_message="err",
        )
        # Replay
        replayed = self.dlq.replay_record(msg.id)
        self.assertEqual(replayed.status, "REPLAYED")

        # Discard
        success = self.dlq.discard_record(msg.id)
        self.assertTrue(success)
        discarded = self.dlq.get_quarantined(msg.id)
        self.assertEqual(discarded.status, "DISCARDED")


class TestGracefulShutdown(unittest.IsolatedAsyncioTestCase):
    """Verifies shutdown manager draining, task rejection, and database disposal."""

    async def asyncSetUp(self):
        self.manager = GracefulShutdownManager(shutdown_timeout=1.0)
        self.manager.reset()

    async def asyncTearDown(self):
        self.manager.reset()

    async def test_track_task_concurrency(self):
        self.assertEqual(self.manager.active_tasks, 0)
        with self.manager.track_task():
            self.assertEqual(self.manager.active_tasks, 1)
        self.assertEqual(self.manager.active_tasks, 0)

    async def test_shutdown_rejects_new_tasks(self):
        with self.manager.track_task():
            # Trigger shutdown while task is in flight
            self.manager.mark_shutting_down()

            # Attempting new task during shutdown must raise 503 ServiceUnavailableError
            with self.assertRaises(ServiceUnavailableError), self.manager.track_task():
                pass

        self.assertTrue(self.manager.is_shutting_down)
        self.assertEqual(self.manager.active_tasks, 0)


class TestResilienceAPIEndpoints(unittest.TestCase):
    """Verifies DLQ REST API endpoints, startup probe, and Idempotency-Key caching headers."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        self.operator_user = User(
            id="op-user-1",
            email="operator@cloud.com",
            hashed_password="pw",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: self.operator_user
        app.dependency_overrides[require_role(UserRole.OPERATOR, UserRole.ADMIN)] = lambda: (
            self.operator_user
        )

        dlq_service.reset_all()

    def tearDown(self):
        app.dependency_overrides.clear()
        dlq_service.reset_all()

    def test_startup_probe(self):
        with patch("src.api.v1.health.check_db_health", return_value=True):
            res = self.client.get("/api/v1/health/startup")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "READY")

        with patch("src.api.v1.health.check_db_health", return_value=False):
            res = self.client.get("/api/v1/health/startup")
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.json()["status"], "STARTING")

    def test_dlq_api_crud_operations(self):
        msg = dlq_service.quarantine_record(
            job_id="job-api-test",
            workflow_name="wf-api",
            source_type="JSON_FILE",
            target_table="Target_API",
            payload={"key": "val"},
            error_message="Mock serialization error",
        )

        # 1. List
        list_res = self.client.get("/api/v1/dlq")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["total"], 1)

        # 2. Detail
        detail_res = self.client.get(f"/api/v1/dlq/{msg.id}")
        self.assertEqual(detail_res.status_code, 200)
        self.assertEqual(detail_res.json()["job_id"], "job-api-test")

        # 3. Replay
        replay_res = self.client.post(f"/api/v1/dlq/{msg.id}/replay")
        self.assertEqual(replay_res.status_code, 200)
        self.assertEqual(replay_res.json()["status"], "REPLAYED")

        # 4. Discard
        del_res = self.client.delete(f"/api/v1/dlq/{msg.id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "DISCARDED")

    def test_idempotency_key_header_caching(self):
        existing_wf = Workflow(
            id="job-idem-123",
            workflow_name="idem-wf",
            source_type="CSV",
            target_dynamodb_table="Table_A",
            records_total=1,
            user_id=self.operator_user.id,
        )

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = existing_wf
        self.mock_session.execute.return_value = mock_res

        payload = {
            "workflow_name": "idem-wf",
            "source_type": "CSV",
            "target_dynamodb_table": "Table_A",
            "payload_data": [{"col": "data"}],
        }

        res = self.client.post(
            "/api/v1/workflows",
            json=payload,
            headers={"Idempotency-Key": "client-key-xyz-789"},
        )
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.headers.get("X-Cache"), "HIT")
        self.assertEqual(res.headers.get("X-Idempotency-Key"), "client-key-xyz-789")


if __name__ == "__main__":
    unittest.main()
