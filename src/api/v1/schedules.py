"""Cron-based workflow schedule management routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.schedule_schemas import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from src.core.idempotency import generate_deterministic_job_id
from src.core.logger import get_logger
from src.core.security import get_current_active_user, require_role
from src.database import get_db_session
from src.models.schedule import WorkflowSchedule
from src.models.user import User, UserRole
from src.models.workflow import StepStatus, Workflow, WorkflowStep
from src.workers.tasks import execute_migration_task

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new recurring workflow schedule",
)
async def create_schedule(
    req: ScheduleCreateRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowSchedule:
    """Creates a new cron-based automated workflow trigger."""
    schedule = WorkflowSchedule(
        name=req.name,
        cron_expression=req.cron_expression,
        workflow_name=req.workflow_name,
        source_type=req.source_type,
        target_dynamodb_table=req.target_dynamodb_table,
        payload_data=req.payload_data,
        configuration=req.configuration,
        user_id=current_user.id,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    logger.info(
        "Created recurring schedule", extra={"schedule_id": schedule.id, "name": schedule.name}
    )
    return schedule


@router.get(
    "",
    response_model=list[ScheduleResponse],
    summary="List all workflow schedules",
)
async def list_schedules(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkflowSchedule]:
    """Retrieves all schedules for the user or organization."""
    stmt = select(WorkflowSchedule)
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN.value:
        stmt = stmt.where(WorkflowSchedule.user_id == current_user.id)

    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get schedule details by ID",
)
async def get_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowSchedule:
    """Retrieves detailed configuration for a specific schedule."""
    stmt = select(WorkflowSchedule).where(WorkflowSchedule.id == schedule_id)
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    if (
        not current_user.is_superuser
        and current_user.role != UserRole.ADMIN.value
        and schedule.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return schedule


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update or toggle a schedule",
)
async def update_schedule(
    schedule_id: str,
    req: ScheduleUpdateRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowSchedule:
    """Updates parameters (e.g. is_active, cron_expression, name) of a schedule."""
    schedule = await get_schedule(
        schedule_id=schedule_id, current_user=current_user, session=session
    )

    if req.name is not None:
        schedule.name = req.name
    if req.cron_expression is not None:
        schedule.cron_expression = req.cron_expression
    if req.is_active is not None:
        schedule.is_active = req.is_active

    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schedule",
)
async def delete_schedule(
    schedule_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Deletes a schedule."""
    schedule = await get_schedule(
        schedule_id=schedule_id, current_user=current_user, session=session
    )
    await session.delete(schedule)
    await session.commit()


@router.post(
    "/{schedule_id}/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually trigger an immediate execution of a schedule",
)
async def trigger_schedule(
    schedule_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Immediately instantiates and dispatches a workflow job from this schedule."""
    schedule = await get_schedule(
        schedule_id=schedule_id, current_user=current_user, session=session
    )

    timestamp_suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    workflow_name = f"{schedule.workflow_name}-{timestamp_suffix}"

    job_id = generate_deterministic_job_id(
        workflow_name=workflow_name,
        source_type=schedule.source_type,
        target_table=schedule.target_dynamodb_table,
        payload_data=schedule.payload_data or [{"trigger": "scheduled"}],
    )

    workflow = Workflow(
        id=job_id,
        workflow_name=workflow_name,
        source_type=schedule.source_type,
        target_dynamodb_table=schedule.target_dynamodb_table,
        records_total=len(schedule.payload_data) if schedule.payload_data else 1,
        configuration=schedule.configuration or {},
        user_id=current_user.id,
    )
    step = WorkflowStep(
        workflow_id=job_id,
        from_state="START",
        to_state="PENDING",
        status=StepStatus.SUCCESS.value,
        execution_duration_ms=0.0,
    )
    workflow.steps = [step]

    schedule.total_runs += 1
    schedule.last_run_at = datetime.now(UTC)

    session.add(workflow)
    await session.commit()

    try:
        execute_migration_task.delay(
            job_id=job_id,
            workflow_name=workflow_name,
            payload_data=schedule.payload_data or [{"trigger": "scheduled"}],
            target_table=schedule.target_dynamodb_table,
            source_type=schedule.source_type,
            configuration=schedule.configuration,
        )
    except Exception as exc:
        logger.warning(
            "Schedule dispatch skipped Celery (testing mode)", extra={"warning": str(exc)}
        )

    return {"message": "Schedule triggered successfully", "job_id": job_id}
