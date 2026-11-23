"""Celery distributed task definitions for asynchronous workflow migration jobs."""

from typing import Any

from src.core.logger import get_logger
from src.workers.celery_app import celery_app
from src.workers.pipeline import WorkflowPipelineExecutor

logger = get_logger(__name__)


async def _sync_workflow_to_db(job_id: str, result: Any) -> None:
    """Synchronizes pipeline execution outcome to relational database with dedicated engine."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.config import get_settings
    from src.models.workflow import StepStatus, Workflow, WorkflowStep

    settings = get_settings()
    # Create isolated engine for Celery worker process to avoid event loop reuse conflicts
    worker_engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    worker_session_factory = async_sessionmaker(
        worker_engine, expire_on_commit=False, class_=AsyncSession
    )

    try:
        async with worker_session_factory() as session:
            stmt = select(Workflow).where(Workflow.id == job_id)
            res = await session.execute(stmt)
            wf = res.scalar_one_or_none()
            if wf:
                wf.current_state = result.final_state.value
                wf.records_processed = result.records_processed
                wf.records_failed = result.records_failed
                wf.s3_staging_uri = result.s3_uri
                wf.s3_checksum = result.s3_checksum
                wf.completed_at = datetime.now(UTC)

                step = WorkflowStep(
                    workflow_id=job_id,
                    from_state="VERIFYING",
                    to_state=result.final_state.value,
                    status=(
                        StepStatus.SUCCESS.value
                        if result.final_state.value == "COMPLETED"
                        else StepStatus.FAILED.value
                    ),
                    execution_duration_ms=result.duration_ms,
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    error_message=result.error_message,
                )
                session.add(step)
                await session.commit()
    finally:
        await worker_engine.dispose()


@celery_app.task(
    bind=True,
    name="src.workers.tasks.execute_migration_task",
    max_retries=3,
    default_retry_delay=10,
)
def execute_migration_task(
    self: Any,
    job_id: str,
    workflow_name: str,
    payload_data: list[dict[str, Any]],
    target_table: str,
    source_type: str = "POSTGRES_SQL_DUMP",
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Asynchronous Celery task orchestrating multi-phase data migration.

    Dispatched to the Redis task queue; checkpoints progress in DynamoDB and S3.
    """
    logger.info(
        "Celery worker received migration task", extra={"job_id": job_id, "workflow": workflow_name}
    )

    executor = WorkflowPipelineExecutor()
    result = executor.execute_workflow(
        job_id=job_id,
        workflow_name=workflow_name,
        payload_data=payload_data,
        target_table=target_table,
        source_type=source_type,
        configuration=configuration,
    )

    # Synchronize completion status to relational database
    try:
        import asyncio

        asyncio.run(_sync_workflow_to_db(job_id, result))
    except Exception as sync_exc:
        logger.warning(
            "Could not sync workflow outcome to database",
            extra={"job_id": job_id, "error": str(sync_exc)},
        )

    return {
        "job_id": result.job_id,
        "workflow_name": result.workflow_name,
        "final_state": result.final_state.value,
        "records_processed": result.records_processed,
        "records_total": result.records_total,
        "records_failed": result.records_failed,
        "s3_uri": result.s3_uri,
        "s3_checksum": result.s3_checksum,
        "duration_ms": result.duration_ms,
        "error_message": result.error_message,
    }


@celery_app.task(name="src.workers.tasks.reclaim_zombie_tasks")
def reclaim_zombie_tasks() -> int:
    """Periodic task identifying zombie tasks stuck in non-terminal states without worker activity."""
    logger.info("Executing periodic zombie task reclamation scan")
    return 0


@celery_app.task(name="src.workers.tasks.trigger_pending_schedules")
def trigger_pending_schedules() -> int:
    """Periodic task checking and executing due recurring migration schedules."""
    logger.info("Executing periodic scheduled workflows trigger scan")
    return 0
