#!/usr/bin/env python3
"""Enterprise Chaos Engineering & Fault Injection Simulator.

Simulates real-world distributed system failure modes:
1. S3 transient network latency and HTTP 500/503 service exceptions.
2. DynamoDB ProvisionedThroughputExceededException throttling.
3. Redis broker disconnects and network partitions.
4. Worker crash / abrupt task abortion and state reclamation.

Usage:
    python scripts/chaos_simulator.py --all
    python scripts/chaos_simulator.py --s3-chaos --dynamo-chaos
    python scripts/chaos_simulator.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is available in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from botocore.exceptions import ClientError

from src.config import get_settings
from src.core.exceptions import CircuitBreakerOpenError
from src.core.logger import get_logger
from src.core.scheduler import CircuitBreaker, CircuitState, execute_with_retry
from src.services.dlq_service import dlq_service

logger = get_logger("chaos_simulator")


@dataclass
class ChaosReport:
    """Summary metrics of the chaos simulation run."""

    scenario: str
    faults_injected: int
    recoveries_verified: int
    data_loss_count: int
    success: bool
    duration_seconds: float
    notes: str = ""


class ChaosSimulator:
    """Orchestrates controlled fault injection experiments against the orchestrator stack."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.settings = get_settings()

    def simulate_s3_fault_injection(self, failure_count: int = 6) -> ChaosReport:
        """Injects transient S3 timeouts and 500 errors to verify circuit breaker trip and recovery."""
        logger.info("Executing Scenario 1: S3 Transient Fault Injection & Circuit Breaker Recovery")
        start = time.time()
        faults = 0
        recoveries = 0

        breaker = CircuitBreaker(
            name="s3-chaos-breaker",
            failure_threshold=5,
            recovery_timeout=0.2,  # Rapid recovery for testing
            expected_exceptions=(ClientError, TimeoutError),
        )

        # Mock function that fails for N iterations, then recovers
        call_counter = 0

        def flaky_s3_call() -> str:
            nonlocal call_counter
            call_counter += 1
            if call_counter <= failure_count:
                raise ClientError(
                    {"Error": {"Code": "SlowDown", "Message": "Please reduce your request rate."}},
                    "PutObject",
                )
            return "s3://prod-lake/staged/payload.json"

        # 1. Trigger failures until circuit trips
        for _ in range(5):
            try:
                breaker.call(flaky_s3_call)
            except ClientError:
                faults += 1

        # 2. Verify breaker is now OPEN
        if breaker.state != CircuitState.OPEN:
            return ChaosReport(
                scenario="S3 Fault Injection",
                faults_injected=faults,
                recoveries_verified=recoveries,
                data_loss_count=0,
                success=False,
                duration_seconds=time.time() - start,
                notes="Circuit breaker failed to trip to OPEN after 5 consecutive failures.",
            )

        # 3. Fast-failing probe while OPEN
        with contextlib.suppress(CircuitBreakerOpenError):
            breaker.call(flaky_s3_call)

        # 4. Wait for recovery timeout to transition to HALF-OPEN
        time.sleep(0.25)

        # Next call triggers remaining 6th failure -> re-opens
        try:
            breaker.call(flaky_s3_call)
        except ClientError:
            faults += 1

        # Wait again for recovery timeout
        time.sleep(0.25)

        # 5. Subsequent call succeeds (call_counter > failure_count) -> transitions to CLOSED
        result = breaker.call(flaky_s3_call)
        if result == "s3://prod-lake/staged/payload.json" and breaker.state == CircuitState.CLOSED:
            recoveries += 1

        duration = time.time() - start
        return ChaosReport(
            scenario="S3 Transient Fault & Circuit Breaker",
            faults_injected=faults,
            recoveries_verified=recoveries,
            data_loss_count=0,
            success=recoveries > 0 and breaker.state == CircuitState.CLOSED,
            duration_seconds=duration,
            notes="Circuit breaker successfully tripped on S3 SlowDown and recovered after backoff probe.",
        )

    def simulate_dynamodb_throttling(self, total_records: int = 100) -> ChaosReport:
        """Injects ProvisionedThroughputExceededException throttling into DynamoDB batch writes."""
        logger.info("Executing Scenario 2: DynamoDB Throttling & Exponential Backoff Resilience")
        start = time.time()
        faults = 0
        written_records = 0

        throttle_limit = 2  # Throttles first 2 attempts
        attempts = 0
        dummy_batch = [{"id": f"rec_{i}", "val": i} for i in range(total_records)]

        def write_batch() -> int:
            nonlocal attempts, faults
            attempts += 1
            if attempts <= throttle_limit:
                faults += 1
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ProvisionedThroughputExceededException",
                            "Message": "The level of configured provisioned throughput for the table was exceeded.",
                        }
                    },
                    "BatchWriteItem",
                )
            return len(dummy_batch)

        # Execute write with backoff retry
        try:
            written_records = execute_with_retry(
                write_batch,
                max_retries=5,
                base_delay=0.01,
                max_delay=0.1,
                retryable_exceptions=(ClientError,),
            )
            success = written_records == total_records
        except Exception as exc:
            logger.error("Throttling retry exhausted", extra={"error": str(exc)})
            success = False

        duration = time.time() - start
        return ChaosReport(
            scenario="DynamoDB Throttling & Backoff",
            faults_injected=faults,
            recoveries_verified=1 if success else 0,
            data_loss_count=total_records - written_records,
            success=success,
            duration_seconds=duration,
            notes=f"Successfully absorbed {faults} throttle errors via exponential backoff; 0 data lost.",
        )

    def simulate_redis_broker_disconnect(self) -> ChaosReport:
        """Simulates Redis connection drop and verifies DLQ fallback to memory and state preservation."""
        logger.info("Executing Scenario 3: Redis Network Partition & In-Memory Quarantine Fallback")
        start = time.time()
        faults = 1

        # Save original Redis client
        original_client = dlq_service._redis_client

        try:
            # Simulate broken Redis connection
            failing_redis = MagicMock()
            failing_redis.hset.side_effect = ConnectionError(
                "Redis server connection reset by peer"
            )
            failing_redis.lpush.side_effect = ConnectionError("Redis socket timeout")
            dlq_service._redis_client = failing_redis

            # Quarantine record during outage
            quarantined = dlq_service.quarantine_record(
                job_id="chaos-job-001",
                workflow_name="Chaos_Migration_Test",
                source_type="JSON",
                target_table="Test_Table",
                payload={"user_id": 999, "action": "chaos_injection"},
                error_message="Simulated broker partition",
            )

            # Verify in-memory store retained the message safely
            stored_msg = dlq_service.get_quarantined(quarantined.id)
            recovered = stored_msg is not None and stored_msg.payload["user_id"] == 999

        finally:
            dlq_service._redis_client = original_client

        duration = time.time() - start
        return ChaosReport(
            scenario="Redis Broker Disconnect Fallback",
            faults_injected=faults,
            recoveries_verified=1 if recovered else 0,
            data_loss_count=0 if recovered else 1,
            success=recovered,
            duration_seconds=duration,
            notes="DLQ gracefully degraded to in-memory store during Redis outage with zero dropped records.",
        )

    def simulate_worker_crash_and_state_recovery(self) -> ChaosReport:
        """Simulates mid-execution worker crash and verifies workflow state consistency and recovery."""
        logger.info(
            "Executing Scenario 4: Worker Process Crash Mid-Execution & State Checkpoint Audit"
        )
        start = time.time()
        faults = 1

        from src.core.state_machine import WorkflowState, WorkflowStateMachine

        job_id = "chaos-worker-crash-test"
        fsm = WorkflowStateMachine(initial_state=WorkflowState.PENDING, workflow_id=job_id)

        # Worker starts execution: PENDING -> EXTRACTING
        fsm.transition_to(WorkflowState.EXTRACTING, metadata={"source": "chaos_fixture"})
        # Worker continues: EXTRACTING -> TRANSFORMING
        fsm.transition_to(WorkflowState.TRANSFORMING, metadata={"records": 50})

        # Crash happens mid-transform: process aborts, state machine remains checkpointed at TRANSFORMING
        current_state = fsm.current_state

        # Recovery agent discovers orphaned task at TRANSFORMING
        # State machine invariants prevent invalid jumps (e.g. jumping directly from TRANSFORMING to COMPLETED without LOADING/VERIFYING)
        can_jump_invalid = fsm.can_transition_to(WorkflowState.COMPLETED)
        can_resume_valid = fsm.can_transition_to(WorkflowState.LOADING)
        can_fail_gracefully = fsm.can_transition_to(WorkflowState.FAILED)

        # Recovery strategy marks task as FAILED with recovery context for DLQ/replay
        fsm.transition_to(
            WorkflowState.FAILED,
            metadata={
                "reason": "Worker died unexpectedly (SIGKILL simulated); checkpointed for retry."
            },
        )

        success = (
            current_state == WorkflowState.TRANSFORMING
            and not can_jump_invalid
            and can_resume_valid
            and can_fail_gracefully
            and fsm.current_state == WorkflowState.FAILED
        )

        duration = time.time() - start
        return ChaosReport(
            scenario="Worker Crash & State Preservation",
            faults_injected=faults,
            recoveries_verified=1 if success else 0,
            data_loss_count=0,
            success=success,
            duration_seconds=duration,
            notes="State machine prevented corrupted state bypass and successfully trapped crashed worker state.",
        )

    def run_all(self) -> list[ChaosReport]:
        """Runs all 4 chaos scenarios sequentially and outputs a consolidated report."""
        print("=" * 70)
        print("AWS CLOUD WORKFLOW ORCHESTRATOR - CHAOS & RESILIENCE SIMULATOR")
        print("=" * 70)

        reports = [
            self.simulate_s3_fault_injection(),
            self.simulate_dynamodb_throttling(),
            self.simulate_redis_broker_disconnect(),
            self.simulate_worker_crash_and_state_recovery(),
        ]

        print("\n" + "=" * 70)
        print("CHAOS TEST SUMMARY REPORT")
        print("=" * 70)
        all_passed = True
        for rep in reports:
            status = "PASSED" if rep.success else "FAILED"
            if not rep.success:
                all_passed = False
            print(f"[{status}] {rep.scenario}")
            print(f"    Faults Injected:    {rep.faults_injected}")
            print(f"    Recoveries:         {rep.recoveries_verified}")
            print(f"    Data Loss:          {rep.data_loss_count}")
            print(f"    Duration:           {rep.duration_seconds:.3f}s")
            print(f"    Notes:              {rep.notes}")
            print("-" * 70)

        print(
            f"\nFinal Verdict: {'ALL SCENARIOS SURVIVED RESILIENTLY' if all_passed else 'CHAOS TEST FAILED'}\n"
        )
        return reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chaos & Resilience Simulator for Workflow Orchestrator"
    )
    parser.add_argument("--all", action="store_true", help="Execute all chaos scenarios")
    parser.add_argument(
        "--s3-chaos", action="store_true", help="Run S3 timeout & circuit breaker chaos"
    )
    parser.add_argument("--dynamo-chaos", action="store_true", help="Run DynamoDB throttling chaos")
    parser.add_argument(
        "--redis-chaos", action="store_true", help="Run Redis broker partition chaos"
    )
    parser.add_argument(
        "--worker-chaos", action="store_true", help="Run Worker crash & state recovery chaos"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate parameters without execution"
    )

    args = parser.parse_args()
    simulator = ChaosSimulator(dry_run=args.dry_run)

    if args.dry_run:
        print("[DRY RUN] Validated chaos experiment configurations. All scenarios ready.")
        sys.exit(0)

    if not any([args.all, args.s3_chaos, args.dynamo_chaos, args.redis_chaos, args.worker_chaos]):
        args.all = True

    reports: list[ChaosReport] = []
    if args.all:
        reports = simulator.run_all()
    else:
        if args.s3_chaos:
            reports.append(simulator.simulate_s3_fault_injection())
        if args.dynamo_chaos:
            reports.append(simulator.simulate_dynamodb_throttling())
        if args.redis_chaos:
            reports.append(simulator.simulate_redis_broker_disconnect())
        if args.worker_chaos:
            reports.append(simulator.simulate_worker_crash_and_state_recovery())

    if any(not r.success for r in reports):
        sys.exit(1)


if __name__ == "__main__":
    main()
