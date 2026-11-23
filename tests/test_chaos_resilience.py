"""Resilience & Chaos Engineering Verification Test Suite.

Validates that the orchestrator engine gracefully handles catastrophic failures:
1. S3 transient timeouts & circuit breaker protection.
2. DynamoDB throttling & jittered exponential backoff.
3. Redis broker disconnects & in-memory DLQ fallback.
4. Worker crash / abrupt task abortion & state ledger consistency.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from src.core.exceptions import CircuitBreakerOpenError
from src.core.scheduler import CircuitBreaker, CircuitState, execute_with_retry
from src.core.state_machine import WorkflowState, WorkflowStateMachine
from src.services.dlq_service import DeadLetterQueueService


class TestS3ChaosAndCircuitBreaker(unittest.TestCase):
    """Verifies S3 outage fault injection and circuit breaker recovery."""

    def test_s3_slowdown_trips_breaker_and_fast_fails(self):
        breaker = CircuitBreaker(
            name="s3-chaos-test",
            failure_threshold=3,
            recovery_timeout=0.2,
            expected_exceptions=(ClientError,),
        )

        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "SlowDown", "Message": "503 Slow Down"}},
            "PutObject",
        )

        # 3 failures trip to OPEN
        for _ in range(3):
            with self.assertRaises(ClientError):
                breaker.call(mock_s3.put_object, Bucket="test", Key="k")

        self.assertEqual(breaker.state, CircuitState.OPEN)

        # Subsequent call fast-fails without hitting mock_s3
        initial_call_count = mock_s3.put_object.call_count
        with self.assertRaises(CircuitBreakerOpenError):
            breaker.call(mock_s3.put_object, Bucket="test", Key="k")

        self.assertEqual(mock_s3.put_object.call_count, initial_call_count)

    def test_s3_breaker_recovers_to_closed_on_half_open_success(self):
        import time

        breaker = CircuitBreaker(
            name="s3-recovery-test",
            failure_threshold=2,
            recovery_timeout=0.05,
            expected_exceptions=(ClientError,),
        )

        mock_call = MagicMock(
            side_effect=[
                ClientError({"Error": {"Code": "InternalError", "Message": "500"}}, "Op"),
                ClientError({"Error": {"Code": "InternalError", "Message": "500"}}, "Op"),
                "s3-success",
            ]
        )

        # Fail twice -> OPEN
        for _ in range(2):
            with self.assertRaises(ClientError):
                breaker.call(mock_call)

        self.assertEqual(breaker.state, CircuitState.OPEN)

        # Wait for recovery timeout
        time.sleep(0.08)

        # Probe succeeds -> transitions to CLOSED
        result = breaker.call(mock_call)
        self.assertEqual(result, "s3-success")
        self.assertEqual(breaker.state, CircuitState.CLOSED)


class TestDynamoDBThrottlingChaos(unittest.TestCase):
    """Verifies DynamoDB ProvisionedThroughputExceededException throttling handling."""

    def test_throttling_triggers_backoff_and_succeeds(self):
        calls = 0

        def flaky_batch_write() -> int:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ProvisionedThroughputExceededException",
                            "Message": "Throttled",
                        }
                    },
                    "BatchWriteItem",
                )
            return 3

        result = execute_with_retry(
            flaky_batch_write,
            max_retries=4,
            base_delay=0.005,
            max_delay=0.05,
            retryable_exceptions=(ClientError,),
        )

        self.assertEqual(result, 3)
        self.assertEqual(calls, 3)

    def test_sustained_throttling_raises_max_retries_exceeded(self):
        def persistently_throttled() -> None:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ProvisionedThroughputExceededException",
                        "Message": "Throttled",
                    }
                },
                "BatchWriteItem",
            )

        with self.assertRaises(ClientError):
            execute_with_retry(
                persistently_throttled,
                max_retries=3,
                base_delay=0.001,
                max_delay=0.01,
                retryable_exceptions=(ClientError,),
            )


class TestRedisBrokerDisconnectAndDLQFallback(unittest.TestCase):
    """Verifies graceful degradation when Redis broker disconnects."""

    def test_dlq_falls_back_to_in_memory_when_redis_drops(self):
        mock_redis = MagicMock()
        mock_redis.hset.side_effect = ConnectionError("Redis cluster unreachable")
        mock_redis.lpush.side_effect = ConnectionError("Redis socket timeout")

        service = DeadLetterQueueService()
        service._redis_client = mock_redis

        # Record must still be stored safely in memory
        quarantined = service.quarantine_record(
            job_id="job-resilience-01",
            workflow_name="Resilience_Workflow",
            source_type="JSON",
            target_table="Target_Table",
            payload={"id": "item-01", "name": "critical-payload"},
            error_message="Simulated DB outage",
        )

        self.assertIsNotNone(quarantined.id)
        retrieved = service.get_quarantined(quarantined.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.payload["id"], "item-01")
        self.assertEqual(retrieved.status, "QUARANTINED")


class TestWorkerCrashAndStateRecovery(unittest.TestCase):
    """Verifies state machine integrity during sudden worker crash."""

    def test_state_machine_prevents_invalid_jump_after_crash(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.PENDING, workflow_id="crash-job-001")
        fsm.transition_to(WorkflowState.EXTRACTING)
        fsm.transition_to(WorkflowState.TRANSFORMING)

        # Worker crashes during transform. FSM remains at TRANSFORMING.
        self.assertEqual(fsm.current_state, WorkflowState.TRANSFORMING)

        # Invariant: Must not jump directly to COMPLETED or VERIFYING
        self.assertFalse(fsm.can_transition_to(WorkflowState.COMPLETED))
        self.assertFalse(fsm.can_transition_to(WorkflowState.VERIFYING))

        # Can legally transition to LOADING or FAILED
        self.assertTrue(fsm.can_transition_to(WorkflowState.LOADING))
        self.assertTrue(fsm.can_transition_to(WorkflowState.FAILED))

        # Recovery marks failed with diagnostic history
        fsm.transition_to(WorkflowState.FAILED, metadata={"error": "Worker SIGKILL detected"})
        self.assertEqual(fsm.current_state, WorkflowState.FAILED)
        self.assertTrue(fsm.is_terminal())


if __name__ == "__main__":
    unittest.main()
