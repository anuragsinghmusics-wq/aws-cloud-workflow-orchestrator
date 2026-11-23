"""User and identity domain models with role-based access control (RBAC)."""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.audit import ApiKey, AuditLog
    from src.models.workflow import Workflow


class UserRole(str, Enum):
    """RBAC roles governing API permissions and workflow control."""

    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class User(Base):
    """User account model for authentication, authorization, and audit attribution."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default=UserRole.OPERATOR.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(
        "Workflow", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "role" not in kwargs:
            kwargs["role"] = UserRole.OPERATOR.value
        if "is_active" not in kwargs:
            kwargs["is_active"] = True
        if "is_superuser" not in kwargs:
            kwargs["is_superuser"] = False
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(UTC)
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = datetime.now(UTC)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} role={self.role!r}>"
