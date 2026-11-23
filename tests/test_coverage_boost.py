"""Targeted unit tests boosting test coverage across core infrastructure components.

Exercises edge cases in:
- src.services.cloudwatch_service
- src.services.dlq_service
- src.core.shutdown
- src.database
- src.api.websocket_manager
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError
from moto import mock_aws

from src.api.websocket_manager import WorkflowWebSocketManager
from src.config import Settings
from src.core.exceptions import AlarmDispatchError
from src.core.shutdown import GracefulShutdownManager
from src.database import check_db_health, drop_models, get_db_session, init_models
from src.services.cloudwatch_service import CloudWatchService
from src.services.dlq_service import DeadLetterMessage, DeadLetterQueueService


class TestCloudWatchServiceCoverage(unittest.TestCase):
    """Exercises alarm creation, logging, and error handling in CloudWatchService with Moto."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()

        self.settings = Settings(
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="testing",
            AWS_SECRET_ACCESS_KEY="testing",
            USE_LOCALSTACK=False,
            CLOUDWATCH_NAMESPACE="TestOrchestrator",
            CLOUDWATCH_LOG_GROUP="/test/orchestrator",
        )
        self.cw = CloudWatchService(settings=self.settings)

    def tearDown(self):
        self.mock_aws.stop()

    def test_create_failure_alarm_success(self):
        self.cw.create_failure_alarm("HighFailureRateAlarm", threshold=5.0)

    def test_create_failure_alarm_client_error_raises_alarm_dispatch_error(self):
        with patch.object(self.cw._cw_client, "put_metric_alarm") as mock_put:
            mock_put.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
                "PutMetricAlarm",
            )
            with self.assertRaises(AlarmDispatchError):
                self.cw.create_failure_alarm("FailedAlarm")

    def test_log_workflow_event_success_and_existing_stream(self):
        # Create log group in moto first
        self.cw._logs_client.create_log_group(logGroupName=self.settings.CLOUDWATCH_LOG_GROUP)

        # First call creates stream and puts event
        self.cw.log_workflow_event("job-stream-01", "Payload extraction completed")

        # Second call to same stream (exercises ResourceAlreadyExistsException branch)
        self.cw.log_workflow_event("job-stream-01", "Transformation completed")

    def test_log_workflow_event_logs_client_error(self):
        with patch.object(self.cw._logs_client, "put_log_events") as mock_put:
            mock_put.side_effect = ClientError(
                {"Error": {"Code": "ServiceUnavailable", "Message": "Busy"}},
                "PutLogEvents",
            )
            # Should not raise, logs warning
            self.cw.log_workflow_event("job-stream-01", "Hello")


class TestDLQServiceCoverage(unittest.TestCase):
    """Exercises DLQ replay, discard, redis listing, and isolation in DeadLetterQueueService."""

    def setUp(self):
        self.dlq = DeadLetterQueueService()
        self.dlq.reset_all()

    def test_replay_record_with_pipeline_executor(self):
        record = self.dlq.quarantine_record(
            job_id="job-dlq-1",
            workflow_name="Pricing_Update",
            source_type="JSON",
            target_table="Products",
            payload={"sku": "prod-100", "price": 49.99},
            error_message="Validation error",
        )

        mock_executor = MagicMock()
        replayed = self.dlq.replay_record(record.id, pipeline_executor=mock_executor)

        self.assertIsNotNone(replayed)
        self.assertEqual(replayed.status, "REPLAYED")
        mock_executor.execute_workflow.assert_called_once()
        exec_args = mock_executor.execute_workflow.call_args[1]
        self.assertEqual(exec_args["target_table"], "Products")
        self.assertEqual(exec_args["payload_data"], [{"sku": "prod-100", "price": 49.99}])

    def test_replay_record_nonexistent_returns_none(self):
        res = self.dlq.replay_record("nonexistent-id")
        self.assertIsNone(res)

    def test_discard_record_success_and_nonexistent(self):
        record = self.dlq.quarantine_record(
            job_id="job-dlq-2",
            workflow_name="Discard_Test",
            source_type="JSON",
            target_table="Users",
            payload={"invalid": True},
            error_message="Malformed",
        )

        success = self.dlq.discard_record(record.id)
        self.assertTrue(success)
        self.assertEqual(self.dlq.get_quarantined(record.id).status, "DISCARDED")

        # Discard non-existent
        self.assertFalse(self.dlq.discard_record("unknown-id"))

    def test_list_quarantined_from_redis_keys(self):
        mock_redis = MagicMock()
        sample_msg = DeadLetterMessage(
            id="msg-redis-1",
            job_id="redis-job",
            workflow_name="Redis_Workflow",
            source_type="JSON",
            target_table="Table",
            payload={"key": "val"},
            error_message="Error from redis",
            error_type="ExecutionError",
            stack_trace=None,
            retry_count=1,
            quarantined_at="2026-11-22T00:00:00Z",
            status="QUARANTINED",
        )
        mock_redis.keys.return_value = ["dlq:record:msg-redis-1"]
        mock_redis.hget.return_value = json.dumps(sample_msg.to_dict())

        service = DeadLetterQueueService()
        service._redis_client = mock_redis

        items, total = service.list_quarantined(job_id="redis-job")
        self.assertEqual(total, 1)
        self.assertEqual(items[0].id, "msg-redis-1")

    def test_get_quarantined_from_redis_cache(self):
        mock_redis = MagicMock()
        sample_msg = DeadLetterMessage(
            id="cached-id-1",
            job_id="cached-job",
            workflow_name="Cached_Workflow",
            source_type="JSON",
            target_table="Table",
            payload={"k": "v"},
            error_message="Err",
            error_type="ExecutionError",
            stack_trace=None,
            retry_count=1,
            quarantined_at="2026-11-22T00:00:00Z",
            status="QUARANTINED",
        )
        mock_redis.hget.return_value = json.dumps(sample_msg.to_dict())

        service = DeadLetterQueueService()
        service._redis_client = mock_redis

        msg = service.get_quarantined("cached-id-1")
        self.assertIsNotNone(msg)
        self.assertEqual(msg.id, "cached-id-1")

    def test_dlq_init_default_redis_client(self):
        with patch("redis.Redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            service = DeadLetterQueueService()
            self.assertIsNotNone(service._redis_client)


class TestGracefulShutdownCoverage(unittest.IsolatedAsyncioTestCase):
    """Exercises full shutdown loop, task draining timeout, and engine cleanup."""

    async def test_shutdown_with_task_draining_and_timeout(self):
        manager = GracefulShutdownManager(shutdown_timeout=0.1)
        manager.track_task()  # 1 active task that does not finish

        mock_engine = AsyncMock()
        with patch("src.database.engine", mock_engine):
            await manager.initiate_shutdown()
            self.assertTrue(manager.is_shutting_down)
            mock_engine.dispose.assert_awaited_once()

    async def test_shutdown_with_task_draining_completes_normally(self):
        manager = GracefulShutdownManager(shutdown_timeout=1.0)
        manager.track_task()

        import asyncio

        async def complete_task_later():
            await asyncio.sleep(0.05)
            manager.untrack_task()

        mock_engine = AsyncMock()
        with patch("src.database.engine", mock_engine):
            asyncio.create_task(complete_task_later())
            await manager.initiate_shutdown()
            self.assertTrue(manager.is_shutting_down)
            self.assertEqual(manager.active_tasks, 0)
            mock_engine.dispose.assert_awaited_once()

    async def test_shutdown_already_in_progress_returns_immediately(self):
        manager = GracefulShutdownManager()
        manager.mark_shutting_down()
        # Should return without waiting
        await manager.initiate_shutdown()
        self.assertTrue(manager.is_shutting_down)


class TestDatabaseHelperCoverage(unittest.IsolatedAsyncioTestCase):
    """Exercises database rollback, health probe, and model init/drop."""

    async def test_db_session_rollback_on_exception(self):
        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_session.__aenter__.return_value = mock_session

        with patch("src.database.AsyncSessionLocal", mock_factory):
            gen = get_db_session()
            session = await gen.__anext__()
            self.assertEqual(session, mock_session)

            with self.assertRaises(RuntimeError):
                await gen.athrow(RuntimeError("Transaction failure simulation"))

            mock_session.rollback.assert_awaited_once()
            mock_session.close.assert_awaited_once()

    async def test_check_db_health_success_and_failure(self):
        # Success case
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_factory = MagicMock(return_value=mock_session)

        is_healthy = await check_db_health(custom_sessionmaker=mock_factory)
        self.assertTrue(is_healthy)

        # Failure case
        mock_failing_session = AsyncMock()
        mock_failing_session.execute.side_effect = ConnectionError("DB down")
        mock_failing_session.__aenter__.return_value = mock_failing_session
        mock_failing_factory = MagicMock(return_value=mock_failing_session)

        is_healthy_fail = await check_db_health(custom_sessionmaker=mock_failing_factory)
        self.assertFalse(is_healthy_fail)

    async def test_init_and_drop_models(self):
        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn

        await init_models(custom_engine=mock_engine)
        self.assertEqual(mock_conn.run_sync.call_count, 1)

        await drop_models(custom_engine=mock_engine)
        self.assertEqual(mock_conn.run_sync.call_count, 2)


class TestWebSocketManagerCoverage(unittest.IsolatedAsyncioTestCase):
    """Exercises WebSocket dead socket removal and client disconnection."""

    async def test_broadcast_prunes_dead_sockets(self):
        manager = WorkflowWebSocketManager()

        good_ws = AsyncMock()
        dead_ws = AsyncMock()
        dead_ws.send_text.side_effect = RuntimeError("Client disconnected abruptly")

        manager._active_connections["job-ws-1"].add(good_ws)
        manager._active_connections["job-ws-1"].add(dead_ws)

        await manager.broadcast("job-ws-1", {"status": "TRANSFORMING"})

        good_ws.send_text.assert_awaited_once()
        dead_ws.send_text.assert_awaited_once()

        # Dead socket must have been removed
        self.assertNotIn(dead_ws, manager._active_connections["job-ws-1"])
        self.assertIn(good_ws, manager._active_connections["job-ws-1"])

    def test_disconnect_removes_job_entry_when_empty(self):
        manager = WorkflowWebSocketManager()
        mock_ws = MagicMock()
        manager._active_connections["job-ws-2"].add(mock_ws)

        manager.disconnect(mock_ws, "job-ws-2")
        self.assertNotIn("job-ws-2", manager._active_connections)

    async def test_broadcast_no_subscribers_noop(self):
        manager = WorkflowWebSocketManager()
        # Should return without exception
        await manager.broadcast("nonexistent-job", {"status": "PENDING"})


if __name__ == "__main__":
    unittest.main()
