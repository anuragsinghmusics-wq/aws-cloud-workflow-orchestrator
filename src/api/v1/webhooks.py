"""Webhook subscription management and delivery testing endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.webhook_schemas import (
    WebhookCreateRequest,
    WebhookResponse,
    WebhookTestRequest,
    WebhookTestResponse,
)
from src.core.logger import get_logger
from src.core.security import get_current_active_user, require_role
from src.database import get_db_session
from src.models.user import User, UserRole
from src.models.webhook import WebhookSubscription
from src.services.webhook_service import webhook_service

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new webhook subscription",
)
async def create_webhook(
    req: WebhookCreateRequest,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookSubscription:
    """Registers an external HTTP(S) endpoint to receive workflow lifecycle events."""
    subscription = WebhookSubscription(
        name=req.name,
        url=req.url,
        events=req.events,
        secret=req.secret or uuid.uuid4().hex,
        user_id=current_user.id,
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)

    logger.info(
        "Registered new webhook subscription",
        extra={"subscription_id": subscription.id, "url": subscription.url},
    )
    return subscription


@router.get(
    "",
    response_model=list[WebhookResponse],
    summary="List all registered webhooks",
)
async def list_webhooks(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WebhookSubscription]:
    """Retrieves all webhooks registered by the authenticated user or organization."""
    stmt = select(WebhookSubscription)
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN.value:
        stmt = stmt.where(WebhookSubscription.user_id == current_user.id)

    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get(
    "/{webhook_id}",
    response_model=WebhookResponse,
    summary="Get webhook details by ID",
)
async def get_webhook(
    webhook_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookSubscription:
    """Retrieves full configuration details for a specific webhook."""
    stmt = select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
    res = await session.execute(stmt)
    webhook = res.scalar_one_or_none()

    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found"
        )

    if (
        not current_user.is_superuser
        and current_user.role != UserRole.ADMIN.value
        and webhook.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return webhook


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook subscription",
)
async def delete_webhook(
    webhook_id: str,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Permanently deletes a registered webhook subscription."""
    webhook = await get_webhook(webhook_id=webhook_id, current_user=current_user, session=session)
    await session.delete(webhook)
    await session.commit()
    logger.info("Deleted webhook subscription", extra={"subscription_id": webhook_id})


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    summary="Send a test ping to verify endpoint connectivity",
)
async def test_webhook(
    webhook_id: str,
    req: WebhookTestRequest | None = None,
    current_user: User = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookTestResponse:
    """Dispatches a simulated event to verify HMAC signing and remote endpoint reachability."""
    webhook = await get_webhook(webhook_id=webhook_id, current_user=current_user, session=session)
    event_type = req.event_type if req else "ping"
    payload = (req.custom_payload if req and req.custom_payload else None) or {
        "message": "Ping from AWS Cloud Workflow Orchestrator",
        "webhook_id": webhook.id,
    }

    success = await webhook_service.dispatch_webhook(
        url=webhook.url,
        event_type=event_type,
        payload=payload,
        secret=webhook.secret,
        max_retries=1,
    )

    return WebhookTestResponse(
        delivery_id=f"test-{uuid.uuid4().hex[:8]}",
        success=success,
        status_code=200 if success else 502,
        message="Ping delivered successfully"
        if success
        else "Failed to deliver ping to target endpoint",
    )
