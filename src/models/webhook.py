"""Webhook subscription model for automated downstream event dispatch."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.user import User


class WebhookSubscription(Base):
    """Registered webhook endpoint receiving HTTP event notifications."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(
        String(128), default=lambda: secrets.token_hex(32), nullable=False
    )
    events: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: ["workflow.completed", "workflow.failed"],
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    total_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    user: Mapped[User] = relationship("User", backref="webhooks", lazy="joined")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "secret" not in kwargs:
            kwargs["secret"] = secrets.token_hex(32)
        if "events" not in kwargs:
            kwargs["events"] = ["workflow.completed", "workflow.failed"]
        if "is_active" not in kwargs:
            kwargs["is_active"] = True
        if "total_deliveries" not in kwargs:
            kwargs["total_deliveries"] = 0
        if "failed_deliveries" not in kwargs:
            kwargs["failed_deliveries"] = 0
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(UTC)
        super().__init__(**kwargs)
