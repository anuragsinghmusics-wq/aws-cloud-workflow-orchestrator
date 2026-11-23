"""Workflow Pipeline Orchestrator and Execution Engine.

Governs multi-phase migration execution:
PENDING -> EXTRACTING -> TRANSFORMING -> LOADING -> VERIFYING -> COMPLETED.

Supports both Celery asynchronous task dispatch and synchronous in-process execution.
"""

import contextlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.config import Settings, get_settings
from src.core.exceptions import (
    InvalidPayloadError,
    OrchestratorError,
)
from src.core.logger import LogContext, get_logger
from src.core.state_machine import WorkflowState, WorkflowStateMachine
from src.services.cloudwatch_service import CloudWatchService
from src.services.dynamodb_service import DynamoDBService
from src.services.s3_service import S3Service

logger = get_logger(__name__)


@dataclass
class PipelineExecutionResult:
    """Detailed summary outcome of a migration pipeline run."""

    job_id: str
    workflow_name: str
    final_state: WorkflowState
    records_total: int
    records_processed: int
    records_failed: int
    s3_uri: str | None
    s3_checksum: str | None
    target_table: str
    duration_ms: float
    error_message: str | None = None
    step_history: list[dict[str, Any]] | None = None


class WorkflowPipelineExecutor:
    """Executes the 6-phase migration pipeline with state machine enforcement and cloud telemetry."""

    def __init__(
        self,
        settings: Settings | None = None,
        s3_service: S3Service | None = None,
        dynamodb_service: DynamoDBService | None = None,
        cloudwatch_service: CloudWatchService | None = None,
    ):
        self.settings = settings or get_settings()
        self.s3_service = s3_service or S3Service(settings=self.settings)
        self.dynamodb_service = dynamodb_service or DynamoDBService(settings=self.settings)
        self.cloudwatch_service = cloudwatch_service or CloudWatchService(settings=self.settings)

    def execute_workflow(
        self,
        job_id: str,
        workflow_name: str,
        payload_data: list[dict[str, Any]],
        target_table: str,
        source_type: str = "POSTGRES_SQL_DUMP",
        configuration: dict[str, Any] | None = None,
    ) -> PipelineExecutionResult:
        """Executes full migration lifecycle from PENDING through COMPLETED (or FAILED)."""
        config = configuration or {}
        batch_size = config.get("batch_size", self.settings.DYNAMODB_MAX_BATCH_SIZE)
        fsm = WorkflowStateMachine(initial_state=WorkflowState.PENDING, workflow_id=job_id)
        start_time = time.time()

        s3_uri: str | None = None
        s3_checksum: str | None = None
        records_processed = 0

        with LogContext(job_id=job_id):
            logger.info(
                "Starting migration pipeline execution",
                extra={
                    "job_id": job_id,
                    "workflow": workflow_name,
                    "target_table": target_table,
                    "records_total": len(payload_data),
                },
            )

            try:
                # -------------------------------------------------------------
                # Phase 1: EXTRACTING (Validation & S3 Staging)
                # -------------------------------------------------------------
                phase_start = time.time()
                fsm.transition_to(WorkflowState.EXTRACTING, metadata={"source_type": source_type})

                if not isinstance(payload_data, list) or len(payload_data) == 0:
                    raise InvalidPayloadError(
                        "Payload data must be a non-empty list of dictionary records."
                    )

                staging_result = self.s3_service.stage_payload(
                    job_id=job_id,
                    payload_data=payload_data,
                )
                s3_uri = staging_result.s3_uri
                s3_checksum = staging_result.checksum
                extract_duration = (time.time() - phase_start) * 1000

                self.cloudwatch_service.record_task_metrics(
                    job_id=job_id,
                    phase="EXTRACTING",
                    duration_ms=extract_duration,
                    records_count=len(payload_data),
                    success=True,
                )

                # Checkpoint in DynamoDB state ledger
                self.dynamodb_service.record_workflow_state(
                    job_id=job_id,
                    state=WorkflowState.EXTRACTING.value,
                    metadata={
                        "workflow_name": workflow_name,
                        "s3_uri": s3_uri,
                        "s3_checksum": s3_checksum,
                        "records_total": len(payload_data),
                        "target_table": target_table,
                    },
                )

                # -------------------------------------------------------------
                # Phase 2: TRANSFORMING (Schema Mapping & Validation)
                # -------------------------------------------------------------
                phase_start = time.time()
                fsm.transition_to(WorkflowState.TRANSFORMING)

                # Retrieve and verify staged payload from S3
                staged_payload = self.s3_service.retrieve_payload(
                    key=staging_result.key,
                    expected_checksum=s3_checksum,
                )

                # Auto-detect target table partition key from payload or configuration
                partition_key = config.get("partition_key")
                if not partition_key:
                    if staged_payload and isinstance(staged_payload[0], dict):
                        if "user_id" in staged_payload[0]:
                            partition_key = "user_id"
                        elif "record_id" in staged_payload[0]:
                            partition_key = "record_id"
                        else:
                            partition_key = "id"
                    else:
                        partition_key = "id"

                # Ensure table exists in DynamoDB
                self.dynamodb_service.ensure_table_exists(
                    table_name=target_table,
                    partition_key=partition_key,
                )

                # Query actual table partition key to avoid any key schema mismatches
                try:
                    table_desc = self.dynamodb_service._client.describe_table(
                        TableName=target_table
                    )
                    hash_keys = [
                        k["AttributeName"]
                        for k in table_desc.get("Table", {}).get("KeySchema", [])
                        if k.get("KeyType") == "HASH"
                    ]
                    actual_pk = hash_keys[0] if hash_keys else partition_key
                except Exception:
                    actual_pk = partition_key

                # Normalization transformation: ensure each record has the required partition key
                transformed_records = []
                for idx, record in enumerate(staged_payload):
                    cleaned = dict(record)
                    pk_value = (
                        cleaned.get(actual_pk)
                        or cleaned.get("id")
                        or cleaned.get("user_id")
                        or cleaned.get("record_id")
                        or f"{job_id}_{idx}"
                    )
                    cleaned[actual_pk] = str(pk_value)
                    if "id" not in cleaned:
                        cleaned["id"] = str(pk_value)
                    cleaned["_migrated_at"] = datetime.now(UTC).isoformat()
                    cleaned["_workflow_id"] = job_id
                    transformed_records.append(cleaned)

                transform_duration = (time.time() - phase_start) * 1000
                self.cloudwatch_service.record_task_metrics(
                    job_id=job_id,
                    phase="TRANSFORMING",
                    duration_ms=transform_duration,
                    records_count=len(transformed_records),
                    success=True,
                )

                # -------------------------------------------------------------
                # Phase 3: LOADING (Batch Write to Target DynamoDB Table)
                # -------------------------------------------------------------
                phase_start = time.time()
                fsm.transition_to(WorkflowState.LOADING)

                batch_result = self.dynamodb_service.batch_write_records(
                    table_name=target_table,
                    items=transformed_records,
                    batch_size=batch_size,
                    max_retries=self.settings.MAX_RETRIES,
                )
                records_processed = batch_result["processed"]
                load_duration = (time.time() - phase_start) * 1000

                self.cloudwatch_service.record_task_metrics(
                    job_id=job_id,
                    phase="LOADING",
                    duration_ms=load_duration,
                    records_count=records_processed,
                    success=True,
                )

                # -------------------------------------------------------------
                # Phase 4: VERIFYING (Integrity & Row Count Audit)
                # -------------------------------------------------------------
                phase_start = time.time()
                fsm.transition_to(WorkflowState.VERIFYING)

                # Verification: records written must equal raw records total
                if records_processed != len(payload_data):
                    raise OrchestratorError(
                        f"Integrity audit mismatch: Expected {len(payload_data)} records, "
                        f"but successfully written was {records_processed}."
                    )

                verify_duration = (time.time() - phase_start) * 1000
                self.cloudwatch_service.record_task_metrics(
                    job_id=job_id,
                    phase="VERIFYING",
                    duration_ms=verify_duration,
                    records_count=records_processed,
                    success=True,
                )

                # -------------------------------------------------------------
                # Phase 5: COMPLETED
                # -------------------------------------------------------------
                fsm.transition_to(WorkflowState.COMPLETED)
                total_duration = (time.time() - start_time) * 1000

                # Final Ledger Checkpoint
                self.dynamodb_service.record_workflow_state(
                    job_id=job_id,
                    state=WorkflowState.COMPLETED.value,
                    expected_version=1,
                    metadata={
                        "records_processed": records_processed,
                        "duration_ms": total_duration,
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )

                logger.info(
                    "Workflow pipeline completed successfully",
                    extra={
                        "job_id": job_id,
                        "duration_ms": total_duration,
                        "records": records_processed,
                    },
                )

                return PipelineExecutionResult(
                    job_id=job_id,
                    workflow_name=workflow_name,
                    final_state=WorkflowState.COMPLETED,
                    records_total=len(payload_data),
                    records_processed=records_processed,
                    records_failed=0,
                    s3_uri=s3_uri,
                    s3_checksum=s3_checksum,
                    target_table=target_table,
                    duration_ms=total_duration,
                    step_history=fsm.get_history(),
                )

            except Exception as exc:
                total_duration = (time.time() - start_time) * 1000
                error_msg = str(exc)
                logger.error(
                    "Workflow pipeline failed during execution",
                    extra={"job_id": job_id, "error": error_msg, "duration_ms": total_duration},
                )

                # Transition to FAILED if not already
                if not fsm.is_terminal():
                    with contextlib.suppress(Exception):
                        fsm.transition_to(WorkflowState.FAILED, metadata={"error": error_msg})

                # Checkpoint failure in DynamoDB ledger
                with contextlib.suppress(Exception):
                    self.dynamodb_service.record_workflow_state(
                        job_id=job_id,
                        state=WorkflowState.FAILED.value,
                        metadata={
                            "error": error_msg,
                            "failed_at": datetime.now(UTC).isoformat(),
                        },
                    )

                self.cloudwatch_service.record_task_metrics(
                    job_id=job_id,
                    phase="FAILED",
                    duration_ms=total_duration,
                    records_count=0,
                    success=False,
                )

                return PipelineExecutionResult(
                    job_id=job_id,
                    workflow_name=workflow_name,
                    final_state=WorkflowState.FAILED,
                    records_total=len(payload_data),
                    records_processed=records_processed,
                    records_failed=len(payload_data) - records_processed,
                    s3_uri=s3_uri,
                    s3_checksum=s3_checksum,
                    target_table=target_table,
                    duration_ms=total_duration,
                    error_message=error_msg,
                    step_history=fsm.get_history(),
                )
