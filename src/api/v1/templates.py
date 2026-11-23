"""Pre-configured workflow migration templates and batch bulk operations."""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.workflow_schemas import WorkflowCreateRequest, WorkflowResponse
from src.core.idempotency import generate_deterministic_job_id
from src.core.security import require_role
from src.database import get_db_session
from src.models.user import User, UserRole
from src.models.workflow import StepStatus, Workflow, WorkflowStep
from src.workers.tasks import execute_migration_task

router = APIRouter()

PRECONFIGURED_TEMPLATES = {
    "postgres-users-to-dynamodb": {
        "id": "postgres-users-to-dynamodb",
        "name": "PostgreSQL Users Table -> DynamoDB User Profiles",
        "description": "Extracts relational user records, normalizes UUIDs, and stages to DynamoDB key-value table.",
        "default_source_type": "POSTGRES_SQL_DUMP",
        "default_target_table": "Enterprise_Users",
        "default_configuration": {"partition_key": "id", "batch_size": 25},
    },
    "mysql-orders-to-dynamodb": {
        "id": "mysql-orders-to-dynamodb",
        "name": "MySQL High-Volume Orders -> DynamoDB E-Commerce",
        "description": "High-throughput migration with batching optimized for order histories and payment records.",
        "default_source_type": "MYSQL_DUMP",
        "default_target_table": "Orders_Ledger",
        "default_configuration": {"partition_key": "order_id", "batch_size": 50},
    },
    "json-event-streams": {
        "id": "json-event-streams",
        "name": "Generic JSON Event Streams -> DynamoDB Analytics",
        "description": "General batch ingestion for application telemetry and audit clickstreams.",
        "default_source_type": "JSON",
        "default_target_table": "Event_Store",
        "default_configuration": {"partition_key": "event_id", "batch_size": 25},
    },
}


class TemplateInstantiateRequest(BaseModel):
    """Payload to instantiate a workflow from a template."""

    model_config = ConfigDict(extra="forbid")

    workflow_name: str = Field(..., min_length=1, max_length=255)
    target_dynamodb_table: str | None = Field(default=None)
    payload_data: list[dict[str, Any]] = Field(default_factory=list)
    configuration_overrides: dict[str, Any] = Field(default_factory=dict)


class BulkWorkflowCreateRequest(BaseModel):
    """Payload for creating multiple workflows in a single batch."""

    model_config = ConfigDict(extra="forbid")

    workflows: list[WorkflowCreateRequest] = Field(..., min_length=1, max_length=20)


@router.get(
    "/templates",
    summary="List pre-configured migration profiles",
)
async def list_templates() -> list[dict[str, Any]]:
    """Returns catalog of built-in migration architecture templates."""
    return list(PRECONFIGURED_TEMPLATES.values())


@router.post(
    "/templates/{template_id}/instantiate",
    response_model=WorkflowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Instantiate a workflow from a pre-configured template",
)
async def instantiate_template(
    template_id: str,
    req: TemplateInstantiateRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> Workflow:
    """Spawns an active workflow pre-populated from an enterprise migration profile."""
    template = PRECONFIGURED_TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    target_table = req.target_dynamodb_table or template["default_target_table"]
    config = dict(template["default_configuration"])
    config.update(req.configuration_overrides)

    job_id = generate_deterministic_job_id(
        workflow_name=req.workflow_name,
        source_type=template["default_source_type"],
        target_table=target_table,
        payload_data=req.payload_data,
    )

    workflow = Workflow(
        id=job_id,
        workflow_name=req.workflow_name,
        source_type=template["default_source_type"],
        target_dynamodb_table=target_table,
        records_total=len(req.payload_data),
        configuration=config,
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

    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)

    with contextlib.suppress(Exception):
        execute_migration_task.delay(
            job_id=job_id,
            workflow_name=req.workflow_name,
            payload_data=req.payload_data,
            target_table=target_table,
            source_type=template["default_source_type"],
            configuration=config,
        )

    return workflow


@router.post(
    "/workflows/bulk",
    response_model=list[dict[str, str]],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk-create multiple migration workflows in a batch transaction",
)
async def bulk_create_workflows(
    req: BulkWorkflowCreateRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, str]]:
    """Enqueues up to 20 workflows in a single transactional batch operation."""
    created_items: list[dict[str, str]] = []

    for item in req.workflows:
        job_id = generate_deterministic_job_id(
            workflow_name=item.workflow_name,
            source_type=item.source_type,
            target_table=item.target_dynamodb_table,
            payload_data=item.payload_data,
        )
        wf = Workflow(
            id=job_id,
            workflow_name=item.workflow_name,
            source_type=item.source_type,
            target_dynamodb_table=item.target_dynamodb_table,
            records_total=len(item.payload_data),
            configuration=item.configuration or {},
            user_id=current_user.id,
        )
        step = WorkflowStep(
            workflow_id=job_id,
            from_state="START",
            to_state="PENDING",
            status=StepStatus.SUCCESS.value,
            execution_duration_ms=0.0,
        )
        wf.steps = [step]
        session.add(wf)
        created_items.append({"job_id": job_id, "workflow_name": item.workflow_name})

        with contextlib.suppress(Exception):
            execute_migration_task.delay(
                job_id=job_id,
                workflow_name=item.workflow_name,
                payload_data=item.payload_data,
                target_table=item.target_dynamodb_table,
                source_type=item.source_type,
                configuration=item.configuration,
            )

    await session.commit()
    return created_items
