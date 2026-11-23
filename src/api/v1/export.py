"""Data export endpoints for workflow history, audit trails, and pre-signed S3 download URLs."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_current_active_user, require_role
from src.database import get_db_session
from src.models.audit import AuditLog
from src.models.user import User, UserRole
from src.models.workflow import Workflow
from src.services.s3_service import S3Service

router = APIRouter()


@router.get(
    "/workflows/csv",
    summary="Export workflow execution history as CSV",
    response_class=Response,
)
async def export_workflows_csv(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Exports workflow records into a downloadable RFC-4180 compliant CSV format."""
    stmt = select(Workflow).order_by(Workflow.created_at.desc())
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN.value:
        stmt = stmt.where(Workflow.user_id == current_user.id)

    res = await session.execute(stmt)
    workflows = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "job_id",
            "workflow_name",
            "source_type",
            "target_dynamodb_table",
            "current_state",
            "records_total",
            "records_processed",
            "records_failed",
            "s3_staging_uri",
            "s3_checksum",
            "created_at",
            "updated_at",
        ]
    )

    for w in workflows:
        writer.writerow(
            [
                w.id,
                w.workflow_name,
                w.source_type,
                w.target_dynamodb_table,
                w.current_state,
                w.records_total,
                w.records_processed,
                w.records_failed,
                w.s3_staging_uri or "",
                w.s3_checksum or "",
                w.created_at.isoformat() if w.created_at else "",
                w.updated_at.isoformat() if w.updated_at else "",
            ]
        )

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="workflows_export.csv"'},
    )


@router.get(
    "/audit-logs/json",
    summary="Export audit trails as structured JSON",
)
async def export_audit_logs_json(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, str | None]]:
    """Exports administrative and state-changing audit log entries for external SIEM / compliance."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(1000)
    res = await session.execute(stmt)
    logs = res.scalars().all()

    return [
        {
            "id": log.id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "user_id": log.user_id,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get(
    "/workflows/{job_id}/payload-download-url",
    summary="Generate pre-signed S3 download URL for workflow raw payload",
)
async def get_payload_download_url(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str | int]:
    """Generates a temporary (1-hour) pre-signed URL allowing direct download of staged S3 artifacts."""
    stmt = select(Workflow).where(Workflow.id == job_id)
    res = await session.execute(stmt)
    workflow = res.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if (
        not current_user.is_superuser
        and current_user.role != UserRole.ADMIN.value
        and workflow.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    s3_key = f"staging/{job_id}/payload.json"
    s3_service = S3Service()
    presigned_url = s3_service.generate_presigned_url(key=s3_key, expiration=3600)

    return {
        "job_id": job_id,
        "s3_key": s3_key,
        "download_url": presigned_url,
        "expires_in_seconds": 3600,
    }
