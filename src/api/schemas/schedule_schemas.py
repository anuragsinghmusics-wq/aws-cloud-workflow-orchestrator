"""Pydantic schemas for recurring cron-based workflow schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreateRequest(BaseModel):
    """Payload to create a recurring workflow schedule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Schedule name")
    cron_expression: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Standard 5-part cron syntax (e.g. 0 */6 * * *)",
    )
    workflow_name: str = Field(
        ..., min_length=1, max_length=255, description="Template workflow name"
    )
    source_type: str = Field(default="JSON", max_length=100)
    target_dynamodb_table: str = Field(..., min_length=3, max_length=255)
    payload_data: list[dict[str, Any]] = Field(
        default_factory=list, description="Template dataset to migrate during each trigger"
    )
    configuration: dict[str, Any] = Field(
        default_factory=dict, description="Worker pipeline options (batch size, etc.)"
    )


class ScheduleUpdateRequest(BaseModel):
    """Payload to update an existing recurring schedule."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    cron_expression: str | None = Field(default=None, min_length=5, max_length=100)
    is_active: bool | None = Field(default=None)


class ScheduleResponse(BaseModel):
    """Output model representing a registered recurring schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    cron_expression: str
    workflow_name: str
    source_type: str
    target_dynamodb_table: str
    is_active: bool
    total_runs: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
