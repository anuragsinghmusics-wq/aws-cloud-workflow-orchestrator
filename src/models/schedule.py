"""Workflow Schedule model for cron-based periodic and automated migrations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.user import User


class WorkflowSchedule(Base):
    """Recurring cron-based schedule triggering workflow execution jobs."""

    __tablename__ = "workflow_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), default="JSON", nullable=False)
    target_dynamodb_table: Mapped[str] = mapped_column(String(255), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    payload_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    total_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", backref="schedules", lazy="joined")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "source_type" not in kwargs:
            kwargs["source_type"] = "JSON"
        if "configuration" not in kwargs:
            kwargs["configuration"] = {}
        if "payload_data" not in kwargs:
            kwargs["payload_data"] = []
        if "is_active" not in kwargs:
            kwargs["is_active"] = True
        if "total_runs" not in kwargs:
            kwargs["total_runs"] = 0
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(UTC)
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = datetime.now(UTC)
        super().__init__(**kwargs)
