"""Asynchronous HMAC-signed Webhook Notification Delivery Engine.

Dispatches real-time workflow lifecycle events to external subscribers:
- Event types: workflow.started, workflow.transitioned, workflow.completed, workflow.failed, dlq.quarantined
- Cryptographic verification via HMAC-SHA256 signature headers (X-Orchestrator-Signature)
- Jittered retry mechanism with exponential backoff on HTTP 5xx and connection drops.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.core.scheduler import calculate_exponential_backoff
from src.models.webhook import WebhookSubscription

logger = get_logger(__name__)


def compute_webhook_signature(payload_bytes: bytes, secret: str) -> str:
    """Computes an HMAC-SHA256 signature for payload verification.

    Returns string format: sha256=<hex_digest>
    """
    mac = hmac.new(secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Validates an incoming signature header in constant time to thwart timing attacks."""
    if not signature_header or not secret:
        return False
    expected = compute_webhook_signature(payload_bytes, secret)
    return hmac.compare_digest(expected, signature_header)


class WebhookService:
    """Orchestrates resilient webhook notifications to subscriber endpoints."""

    def __init__(self, default_timeout: float = 5.0):
        self.default_timeout = default_timeout

    async def dispatch_webhook(
        self,
        url: str,
        event_type: str,
        payload: dict[str, Any],
        secret: str | None = None,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Dispatches an HTTP POST event to a single subscriber with retries."""
        delivery_id = f"del-{uuid.uuid4()}"
        timestamp = datetime.now(UTC).isoformat()

        body = {
            "id": delivery_id,
            "event": event_type,
            "timestamp": timestamp,
            "data": payload,
        }
        raw_bytes = json.dumps(body, sort_keys=True).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AWS-Cloud-Workflow-Orchestrator/1.0",
            "X-Orchestrator-Event": event_type,
            "X-Orchestrator-Delivery": delivery_id,
            "X-Orchestrator-Timestamp": timestamp,
        }
        if secret:
            headers["X-Orchestrator-Signature"] = compute_webhook_signature(raw_bytes, secret)

        async def _do_post(http_client: httpx.AsyncClient) -> bool:
            for attempt in range(max_retries + 1):
                try:
                    res = await http_client.post(
                        url,
                        content=raw_bytes,
                        headers=headers,
                        timeout=self.default_timeout,
                    )
                    if 200 <= res.status_code < 300:
                        logger.info(
                            "Webhook delivered successfully",
                            extra={
                                "delivery_id": delivery_id,
                                "url": url,
                                "event": event_type,
                                "status": res.status_code,
                            },
                        )
                        return True
                    logger.warning(
                        "Webhook target responded with non-2xx status",
                        extra={
                            "delivery_id": delivery_id,
                            "url": url,
                            "status": res.status_code,
                            "attempt": attempt,
                        },
                    )
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    logger.warning(
                        "Webhook delivery failed with network error",
                        extra={"delivery_id": delivery_id, "url": url, "error": str(exc)},
                    )

                if attempt < max_retries:
                    delay = calculate_exponential_backoff(
                        attempt + 1, base_delay=0.2, max_delay=3.0
                    )
                    await asyncio.sleep(delay)
            return False

        if client is not None:
            return await _do_post(client)

        async with httpx.AsyncClient() as managed_client:
            return await _do_post(managed_client)

    async def broadcast_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session: AsyncSession,
        client: httpx.AsyncClient | None = None,
    ) -> int:
        """Dispatches an event to all active subscriptions registered for this event type."""
        stmt = select(WebhookSubscription).where(WebhookSubscription.is_active.is_(True))
        result = await session.execute(stmt)
        subscriptions = result.scalars().all()

        matching = [sub for sub in subscriptions if event_type in (sub.events or [])]
        if not matching:
            return 0

        dispatched_count = 0
        for sub in matching:
            success = await self.dispatch_webhook(
                url=sub.url,
                event_type=event_type,
                payload=payload,
                secret=sub.secret,
                client=client,
            )
            sub.total_deliveries += 1
            if not success:
                sub.failed_deliveries += 1
            sub.last_delivery_at = datetime.now(UTC)
            dispatched_count += 1

        await session.commit()
        return dispatched_count


# Global singleton instance
webhook_service = WebhookService()
