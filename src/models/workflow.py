"""Workflow and step execution domain models representing orchestrated state machine jobs."""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.state_machine import WorkflowState
from src.database import Base

if TYPE_CHECKING:
    from src.models.user import User


class StepStatus(str, Enum):
    """Execution status for an individual workflow step or phase."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    SKIPPED = "SKIPPED"


class Workflow(Base):
    """Top-level record for an orchestrated data migration job."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_dynamodb_table: Mapped[str] = mapped_column(String(255), nullable=False)
    current_state: Mapped[str] = mapped_column(
        String(50), default=WorkflowState.PENDING.value, index=True, nullable=False
    )
    records_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AWS Staging Artifacts
    s3_staging_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    s3_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Configuration & Error context
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Ownership & Timestamps
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="workflows")
    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.started_at",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "current_state" not in kwargs:
            kwargs["current_state"] = WorkflowState.PENDING.value
        if "records_total" not in kwargs:
            kwargs["records_total"] = 0
        if "records_processed" not in kwargs:
            kwargs["records_processed"] = 0
        if "records_failed" not in kwargs:
            kwargs["records_failed"] = 0
        if "configuration" not in kwargs:
            kwargs["configuration"] = {}
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(UTC)
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = datetime.now(UTC)
        super().__init__(**kwargs)

    @property
    def progress_percentage(self) -> float:
        """Calculates workflow execution progress from 0.0 to 100.0%."""
        if self.records_total <= 0:
            return 100.0 if self.current_state == WorkflowState.COMPLETED.value else 0.0
        return round((self.records_processed / self.records_total) * 100.0, 2)

    def __repr__(self) -> str:
        return (
            f"<Workflow id={self.id!r} name={self.workflow_name!r} "
            f"state={self.current_state!r} progress={self.progress_percentage}%>"
        )


class WorkflowStep(Base):
    """Detailed audit history for each state transition in a workflow."""

    __tablename__ = "workflow_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default=StepStatus.IN_PROGRESS.value, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="steps")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = StepStatus.IN_PROGRESS.value
        if "started_at" not in kwargs:
            kwargs["started_at"] = datetime.now(UTC)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<WorkflowStep id={self.id!r} {self.from_state} -> {self.to_state} "
            f"status={self.status!r}>"
        )
