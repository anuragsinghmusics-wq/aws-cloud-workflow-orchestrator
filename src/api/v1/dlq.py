"""Dead-Letter Queue (DLQ) Management and Recovery API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.core.security import require_role
from src.models.user import User, UserRole
from src.services.dlq_service import dlq_service

router = APIRouter()


@router.get(
    "",
    summary="List quarantined dead-letter records with filtering and pagination",
)
async def list_quarantined_records(
    workflow_id: str | None = Query(default=None, description="Filter by workflow/job ID"),
    status: str | None = Query(
        default=None, description="Filter by status (QUARANTINED, REPLAYED, DISCARDED)"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Retrieves paginated list of failed migration records quarantined in the DLQ."""
    items, total = dlq_service.list_quarantined(
        job_id=workflow_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [item.to_dict() for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{record_id}",
    summary="Get single quarantined dead-letter record details",
)
async def get_quarantined_record_detail(
    record_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Retrieves full stack trace, payload, and failure context for a quarantined record."""
    msg = dlq_service.get_quarantined(record_id)
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dead letter record '{record_id}' not found.",
        )
    return msg.to_dict()


@router.post(
    "/{record_id}/replay",
    summary="Replay a quarantined record",
)
async def replay_quarantined_record(
    record_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Re-attempts processing of a quarantined record and marks its status as REPLAYED."""
    msg = dlq_service.replay_record(record_id)
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dead letter record '{record_id}' not found.",
        )
    return {
        "status": "REPLAYED",
        "record_id": record_id,
        "message": f"Record '{record_id}' successfully marked for replay.",
        "item": msg.to_dict(),
    }


@router.delete(
    "/{record_id}",
    summary="Discard a quarantined dead-letter record",
)
async def discard_quarantined_record(
    record_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Marks a quarantined record as permanently DISCARDED."""
    success = dlq_service.discard_record(record_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dead letter record '{record_id}' not found.",
        )
    return {
        "status": "DISCARDED",
        "record_id": record_id,
        "message": f"Record '{record_id}' discarded successfully.",
    }
