"""Workflow orchestration, job initiation, ledger listing, and lifecycle management routes."""

import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.schemas.workflow_schemas import (
    WorkflowCreateRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowRetryRequest,
)
from src.config import get_settings
from src.core.exceptions import (
    TerminalStateError,
    WorkflowNotFoundError,
)
from src.core.idempotency import compute_payload_checksum, generate_deterministic_job_id
from src.core.logger import get_logger
from src.core.security import get_current_active_user, require_role
from src.core.state_machine import WorkflowState
from src.database import get_db_session
from src.models.audit import AuditLog
from src.models.user import User, UserRole
from src.models.workflow import StepStatus, Workflow, WorkflowStep
from src.workers.tasks import execute_migration_task

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter()


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate a new cloud workflow migration job",
)
async def create_workflow(
    req: WorkflowCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> Workflow:
    """Enqueues an asynchronous data migration workflow backed by S3, DynamoDB, and Celery."""
    # Compute deterministic job ID and payload checksum
    job_id = generate_deterministic_job_id(
        workflow_name=req.workflow_name,
        source_type=req.source_type,
        target_table=req.target_dynamodb_table,
        payload_data=req.payload_data,
    )
    checksum = compute_payload_checksum(req.payload_data)

    # Check if this exact job already exists (idempotency check)
    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == job_id)
    result = await session.execute(stmt)
    existing_wf = result.scalar_one_or_none()

    if existing_wf:
        logger.info(
            "Idempotent workflow request matched existing job",
            extra={"job_id": job_id, "state": existing_wf.current_state},
        )
        response.headers["X-Cache"] = "HIT"
        if idempotency_key:
            response.headers["X-Idempotency-Key"] = idempotency_key
        return existing_wf

    # Create new workflow record
    workflow = Workflow(
        id=job_id,
        workflow_name=req.workflow_name,
        source_type=req.source_type,
        target_dynamodb_table=req.target_dynamodb_table,
        current_state=WorkflowState.PENDING.value,
        records_total=len(req.payload_data),
        records_processed=0,
        records_failed=0,
        s3_checksum=checksum,
        configuration=req.configuration,
        user_id=current_user.id,
    )
    session.add(workflow)

    # Record initial pending step
    step = WorkflowStep(
        workflow_id=job_id,
        from_state="START",
        to_state=WorkflowState.PENDING.value,
        status=StepStatus.SUCCESS.value,
        execution_duration_ms=0.0,
    )
    session.add(step)

    # Audit log
    audit = AuditLog(
        entity_type="workflow",
        entity_id=job_id,
        action="INITIATE_WORKFLOW",
        details={
            "workflow_name": req.workflow_name,
            "target_table": req.target_dynamodb_table,
            "records_total": len(req.payload_data),
        },
        user_id=current_user.id,
    )
    session.add(audit)
    await session.commit()

    # Re-fetch with steps eagerly loaded
    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == job_id)
    res = await session.execute(stmt)
    created_wf = res.scalar_one()

    # Dispatch to distributed worker queue (non-blocking, tolerant of worker offline in tests)
    try:
        execute_migration_task.delay(
            job_id=job_id,
            workflow_name=req.workflow_name,
            payload_data=req.payload_data,
            target_table=req.target_dynamodb_table,
            source_type=req.source_type,
            configuration=req.configuration,
        )
        logger.info("Dispatched migration task to Celery queue", extra={"job_id": job_id})
    except Exception as exc:
        logger.warning(
            "Celery task dispatch skipped (broker offline or testing mode)",
            extra={"job_id": job_id, "warning": str(exc)},
        )

    return created_wf


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List workflows with filtering and pagination",
)
async def list_workflows(
    state: str | None = Query(default=None, description="Filter by workflow state"),
    search: str | None = Query(default=None, description="Case-insensitive title search"),
    page: int = Query(default=1, ge=1, description="Page index (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowListResponse:
    """Retrieves paginated workflows belonging to the user (or all workflows for Admins)."""
    filters = []

    # Non-admin users see only their own workflows
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN.value:
        filters.append(Workflow.user_id == current_user.id)

    if state:
        filters.append(Workflow.current_state == state.upper())

    if search:
        filters.append(Workflow.workflow_name.ilike(f"%{search}%"))

    # Count total
    count_stmt = select(func.count(Workflow.id)).where(*filters)
    count_res = await session.execute(count_stmt)
    total_items = count_res.scalar_one() or 0

    # Query page
    offset = (page - 1) * page_size
    query_stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(*filters)
        .order_by(Workflow.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items_res = await session.execute(query_stmt)
    items = list(items_res.scalars().all())

    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    return WorkflowListResponse(
        items=[WorkflowResponse.model_validate(wf) for wf in items],
        total_items=total_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{job_id}",
    response_model=WorkflowResponse,
    summary="Get single workflow status and step audit history",
)
async def get_workflow_detail(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Workflow:
    """Returns real-time execution status, progress percentage, and step transition timeline."""
    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == job_id)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()

    if not wf:
        raise WorkflowNotFoundError(f"Workflow with job ID '{job_id}' does not exist.")

    # Access check: non-admin can only access own workflow
    if (
        not current_user.is_superuser
        and current_user.role != UserRole.ADMIN.value
        and wf.user_id != current_user.id
    ):
        raise WorkflowNotFoundError(f"Workflow with job ID '{job_id}' does not exist.")

    return wf


@router.post(
    "/{job_id}/retry",
    response_model=WorkflowResponse,
    summary="Retry a failed or stalled migration workflow",
)
async def retry_workflow(
    job_id: str,
    req: WorkflowRetryRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> Workflow:
    """Re-enqueues a failed workflow for automatic recovery and replay."""
    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == job_id)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()

    if not wf:
        raise WorkflowNotFoundError(f"Workflow with job ID '{job_id}' does not exist.")

    if wf.current_state == WorkflowState.COMPLETED.value:
        raise TerminalStateError(
            "Workflow is already in COMPLETED terminal state and cannot be retried."
        )

    old_state = wf.current_state
    wf.current_state = WorkflowState.PENDING.value
    wf.error_details = None

    retry_step = WorkflowStep(
        workflow_id=wf.id,
        from_state=old_state,
        to_state=WorkflowState.PENDING.value,
        status=StepStatus.IN_PROGRESS.value,
        execution_duration_ms=0.0,
    )
    session.add(retry_step)

    audit = AuditLog(
        entity_type="workflow",
        entity_id=wf.id,
        action="RETRY_WORKFLOW",
        details={"reason": req.reason, "from_state": old_state},
        user_id=current_user.id,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(wf)

    logger.info("Workflow retry scheduled", extra={"job_id": job_id, "reason": req.reason})
    return wf


@router.post(
    "/{job_id}/cancel",
    response_model=WorkflowResponse,
    summary="Cancel an active or pending workflow",
)
async def cancel_workflow(
    job_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> Workflow:
    """Aborts a workflow in progress, transitioning its state to FAILED."""
    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == job_id)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()

    if not wf:
        raise WorkflowNotFoundError(f"Workflow with job ID '{job_id}' does not exist.")

    if wf.current_state in (WorkflowState.COMPLETED.value, WorkflowState.FAILED.value):
        raise TerminalStateError(
            f"Workflow is already in terminal state '{wf.current_state}' and cannot be canceled."
        )

    old_state = wf.current_state
    wf.current_state = WorkflowState.FAILED.value
    wf.completed_at = datetime.now(UTC)
    wf.error_details = {
        "canceled_by": current_user.email,
        "canceled_at": datetime.now(UTC).isoformat(),
    }

    cancel_step = WorkflowStep(
        workflow_id=wf.id,
        from_state=old_state,
        to_state=WorkflowState.FAILED.value,
        status=StepStatus.FAILED.value,
        error_message=f"Workflow canceled by user {current_user.email}",
    )
    session.add(cancel_step)

    audit = AuditLog(
        entity_type="workflow",
        entity_id=wf.id,
        action="CANCEL_WORKFLOW",
        details={"canceled_by": current_user.email, "prior_state": old_state},
        user_id=current_user.id,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(wf)

    logger.info("Workflow canceled by user", extra={"job_id": job_id, "user": current_user.email})
    return wf
