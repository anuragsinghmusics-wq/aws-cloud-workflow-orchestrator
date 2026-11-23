"""Pydantic schemas for Webhook registration, configuration, and event inspection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebhookCreateRequest(BaseModel):
    """Payload for registering a new webhook subscription endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable webhook name")
    url: str = Field(..., min_length=8, max_length=2048, description="Target HTTP(S) endpoint URL")
    events: list[str] = Field(
        default=["workflow.completed", "workflow.failed"],
        description="List of event names this webhook listens to",
    )
    secret: str | None = Field(
        default=None,
        max_length=128,
        description="Optional shared secret for HMAC-SHA256 signature verification. Auto-generated if omitted.",
    )


class WebhookResponse(BaseModel):
    """Schema returned when retrieving webhook subscription details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    events: list[str]
    is_active: bool
    total_deliveries: int
    failed_deliveries: int
    last_delivery_at: datetime | None
    created_at: datetime


class WebhookTestRequest(BaseModel):
    """Request payload for firing an on-demand test ping to a webhook endpoint."""

    event_type: str = Field(default="ping", description="Event type to simulate")
    custom_payload: dict[str, Any] | None = Field(
        default=None, description="Optional custom test payload"
    )


class WebhookTestResponse(BaseModel):
    """Outcome of an on-demand webhook delivery probe."""

    delivery_id: str
    success: bool
    status_code: int | None
    message: str
