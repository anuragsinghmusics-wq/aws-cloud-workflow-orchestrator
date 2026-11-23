"""Unit and integration tests for Week 4 Day 24-25 Advanced Features.

Validates:
1. Webhook Notification Engine & HMAC-SHA256 signature verification.
2. Webhook subscription REST endpoints (/api/v1/webhooks).
3. Recurring workflow schedules REST endpoints (/api/v1/schedules).
4. Data export endpoints (CSV history, JSON audit, S3 pre-signed URLs).
5. Pre-configured templates & bulk workflow creation.
6. Celery Beat periodic tasks.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from src.core.security import get_current_active_user, require_role
from src.database import get_db_session
from src.main import app
from src.models.audit import AuditLog
from src.models.schedule import WorkflowSchedule
from src.models.user import User, UserRole
from src.models.webhook import WebhookSubscription
from src.models.workflow import Workflow
from src.services.webhook_service import (
    WebhookService,
    compute_webhook_signature,
    verify_webhook_signature,
)
from src.workers.tasks import reclaim_zombie_tasks, trigger_pending_schedules


class TestWebhookServiceUnit(unittest.IsolatedAsyncioTestCase):
    """Unit tests for cryptographic HMAC signature verification and resilient HTTP dispatch."""

    def test_compute_and_verify_signature(self):
        payload = b'{"event":"workflow.completed","job_id":"test-123"}'
        secret = "super-secret-hmac-key"

        sig = compute_webhook_signature(payload, secret)
        self.assertTrue(sig.startswith("sha256="))

        # Verification succeeds with matching secret
        self.assertTrue(verify_webhook_signature(payload, sig, secret))

        # Verification fails with wrong secret
        self.assertFalse(verify_webhook_signature(payload, sig, "wrong-key"))

        # Verification fails if payload altered
        altered = b'{"event":"workflow.completed","job_id":"hacked"}'
        self.assertFalse(verify_webhook_signature(altered, sig, secret))

    async def test_dispatch_webhook_success(self):
        service = WebhookService()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(status_code=200)
        mock_client.post.return_value = mock_response

        success = await service.dispatch_webhook(
            url="https://webhook.site/test",
            event_type="workflow.completed",
            payload={"job_id": "test-job"},
            secret="test-secret",
            max_retries=1,
            client=mock_client,
        )

        self.assertTrue(success)
        mock_client.post.assert_awaited_once()
        headers = mock_client.post.call_args[1]["headers"]
        self.assertIn("X-Orchestrator-Signature", headers)
        self.assertEqual(headers["X-Orchestrator-Event"], "workflow.completed")

    async def test_broadcast_event_matches_subscriptions(self):
        service = WebhookService()
        sub1 = WebhookSubscription(
            id="sub-1",
            name="Slack Alerts",
            url="https://hooks.slack.com/services/1",
            events=["workflow.completed", "workflow.failed"],
            secret="sec1",
            user_id="user-1",
        )
        sub2 = WebhookSubscription(
            id="sub-2",
            name="Metrics Webhook",
            url="https://metrics.io/webhook",
            events=["workflow.started"],  # Does not match workflow.completed
            secret="sec2",
            user_id="user-1",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sub1, sub2]
        mock_session.execute.return_value = mock_result

        with patch.object(service, "dispatch_webhook", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.return_value = True
            count = await service.broadcast_event(
                event_type="workflow.completed",
                payload={"job_id": "job-100"},
                session=mock_session,
            )

            self.assertEqual(count, 1)
            mock_dispatch.assert_awaited_once()
            self.assertEqual(sub1.total_deliveries, 1)
            self.assertEqual(sub2.total_deliveries, 0)


class TestWebhooksAPI(unittest.TestCase):
    """Integration tests for Webhook subscription management API endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        self.user = User(
            id="user-wh-1",
            email="developer@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: self.user
        app.dependency_overrides[require_role(UserRole.OPERATOR, UserRole.ADMIN)] = lambda: (
            self.user
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_create_webhook_subscription(self):
        async def mock_refresh(instance):
            instance.id = "wh-sub-1"
            instance.created_at = datetime.now(UTC)
            instance.is_active = True
            instance.total_deliveries = 0
            instance.failed_deliveries = 0

        self.mock_session.refresh.side_effect = mock_refresh

        res = self.client.post(
            "/api/v1/webhooks",
            json={
                "name": "CI Pipeline Webhook",
                "url": "https://ci.company.com/webhook",
                "events": ["workflow.completed"],
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["name"], "CI Pipeline Webhook")
        self.assertTrue(data["is_active"])

    def test_list_webhooks(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            WebhookSubscription(
                id="wh-sub-2",
                name="Datadog Alert",
                url="https://api.datadoghq.com/webhook",
                events=["workflow.failed"],
                secret="secret-key",
                user_id=self.user.id,
                created_at=datetime.now(UTC),
            )
        ]
        self.mock_session.execute.return_value = mock_result

        res = self.client.get("/api/v1/webhooks")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Datadog Alert")

    @patch("src.api.v1.webhooks.webhook_service.dispatch_webhook", new_callable=AsyncMock)
    def test_test_webhook_ping(self, mock_dispatch):
        mock_dispatch.return_value = True

        webhook = WebhookSubscription(
            id="wh-sub-3",
            name="Test Webhook",
            url="https://webhook.site/probe",
            events=["workflow.completed"],
            secret="secret",
            user_id=self.user.id,
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = webhook
        self.mock_session.execute.return_value = mock_result

        res = self.client.post(
            "/api/v1/webhooks/wh-sub-3/test",
            json={"event_type": "ping"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status_code"], 200)


class TestSchedulesAPI(unittest.TestCase):
    """Integration tests for Workflow Schedule management endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        self.user = User(
            id="user-sched-1",
            email="scheduler@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: self.user
        app.dependency_overrides[require_role(UserRole.OPERATOR, UserRole.ADMIN)] = lambda: (
            self.user
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_create_schedule(self):
        async def mock_refresh(instance):
            instance.id = "sched-uuid-1"
            instance.created_at = datetime.now(UTC)
            instance.is_active = True
            instance.total_runs = 0

        self.mock_session.refresh.side_effect = mock_refresh

        res = self.client.post(
            "/api/v1/schedules",
            json={
                "name": "Daily User Sync",
                "cron_expression": "0 0 * * *",
                "workflow_name": "Scheduled_User_Sync",
                "source_type": "JSON",
                "target_dynamodb_table": "Users_Daily",
                "payload_data": [{"id": "1", "name": "Scheduled"}],
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["name"], "Daily User Sync")
        self.assertEqual(data["cron_expression"], "0 0 * * *")

    def test_trigger_schedule_on_demand(self):
        sched = WorkflowSchedule(
            id="sched-uuid-2",
            name="Hourly Orders Sync",
            cron_expression="0 * * * *",
            workflow_name="Hourly_Orders",
            source_type="JSON",
            target_dynamodb_table="Orders_Table",
            payload_data=[{"order_id": 99}],
            configuration={},
            user_id=self.user.id,
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sched
        self.mock_session.execute.return_value = mock_result

        with patch("src.api.v1.schedules.execute_migration_task.delay") as mock_delay:
            res = self.client.post("/api/v1/schedules/sched-uuid-2/trigger")
            self.assertEqual(res.status_code, 202)
            data = res.json()
            self.assertIn("job_id", data)
            mock_delay.assert_called_once()


class TestExportAndTemplatesAPI(unittest.TestCase):
    """Integration tests for CSV/JSON exports, pre-signed URLs, templates, and bulk creation."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        self.admin_user = User(
            id="user-admin-1",
            email="admin@company.com",
            hashed_password="hash",
            role=UserRole.ADMIN.value,
            is_active=True,
            is_superuser=True,
        )

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: self.admin_user
        app.dependency_overrides[require_role(UserRole.OPERATOR, UserRole.ADMIN)] = lambda: (
            self.admin_user
        )
        app.dependency_overrides[require_role(UserRole.ADMIN)] = lambda: self.admin_user

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_export_workflows_csv(self):
        wf = Workflow(
            id="job-export-1",
            workflow_name="Exported Workflow",
            source_type="JSON",
            target_dynamodb_table="Analytics",
            current_state="COMPLETED",
            records_total=10,
            records_processed=10,
            records_failed=0,
            user_id=self.admin_user.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [wf]
        self.mock_session.execute.return_value = mock_result

        res = self.client.get("/api/v1/export/workflows/csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers["content-type"])
        self.assertIn("job-export-1", res.text)
        self.assertIn("Exported Workflow", res.text)

    def test_export_audit_logs_json(self):
        log = AuditLog(
            id="audit-log-1",
            action="WORKFLOW_INITIATED",
            entity_type="Workflow",
            entity_id="job-100",
            user_id=self.admin_user.id,
            ip_address="127.0.0.1",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log]
        self.mock_session.execute.return_value = mock_result

        res = self.client.get("/api/v1/export/audit-logs/json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "WORKFLOW_INITIATED")

    @patch("src.services.s3_service.S3Service.generate_presigned_url")
    def test_get_payload_download_url(self, mock_presign):
        mock_presign.return_value = (
            "https://s3.amazonaws.com/test-bucket/staging/job-1/payload.json?AWSAccessKeyId=..."
        )

        wf = Workflow(
            id="job-1",
            workflow_name="Downloadable",
            source_type="JSON",
            target_dynamodb_table="Table",
            user_id=self.admin_user.id,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_result

        res = self.client.get("/api/v1/export/workflows/job-1/payload-download-url")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["job_id"], "job-1")
        self.assertIn("download_url", data)

    def test_list_templates(self):
        res = self.client.get("/api/v1/templates")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(len(data), 3)
        ids = [t["id"] for t in data]
        self.assertIn("postgres-users-to-dynamodb", ids)
        self.assertIn("mysql-orders-to-dynamodb", ids)

    @patch("src.api.v1.templates.execute_migration_task")
    def test_instantiate_template(self, mock_celery):
        async def mock_refresh(instance):
            instance.id = "instantiated-job-1"
            instance.current_state = "PENDING"
            instance.records_total = 1
            instance.records_processed = 0
            instance.records_failed = 0
            instance.created_at = datetime.now(UTC)
            instance.updated_at = datetime.now(UTC)

        self.mock_session.refresh.side_effect = mock_refresh

        res = self.client.post(
            "/api/v1/templates/postgres-users-to-dynamodb/instantiate",
            json={
                "workflow_name": "Users_Batch_01",
                "payload_data": [{"id": 1, "username": "bob"}],
            },
        )
        self.assertEqual(res.status_code, 202)
        data = res.json()
        self.assertEqual(data["workflow_name"], "Users_Batch_01")
        self.assertEqual(data["source_type"], "POSTGRES_SQL_DUMP")

    @patch("src.api.v1.templates.execute_migration_task")
    def test_bulk_create_workflows(self, mock_celery):
        res = self.client.post(
            "/api/v1/workflows/bulk",
            json={
                "workflows": [
                    {
                        "workflow_name": "Bulk_Job_1",
                        "source_type": "JSON",
                        "target_dynamodb_table": "Bulk_Table",
                        "payload_data": [{"col": "a"}],
                    },
                    {
                        "workflow_name": "Bulk_Job_2",
                        "source_type": "JSON",
                        "target_dynamodb_table": "Bulk_Table",
                        "payload_data": [{"col": "b"}],
                    },
                ]
            },
        )
        self.assertEqual(res.status_code, 202)
        data = res.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["workflow_name"], "Bulk_Job_1")
        self.assertEqual(data[1]["workflow_name"], "Bulk_Job_2")


class TestCeleryPeriodicTasks(unittest.TestCase):
    """Verifies Celery Beat periodic task handlers execute cleanly."""

    def test_periodic_reclaim_zombie_tasks(self):
        res = reclaim_zombie_tasks()
        self.assertEqual(res, 0)

    def test_periodic_trigger_pending_schedules(self):
        res = trigger_pending_schedules()
        self.assertEqual(res, 0)


if __name__ == "__main__":
    unittest.main()
