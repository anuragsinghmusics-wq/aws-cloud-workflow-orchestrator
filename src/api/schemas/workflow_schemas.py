"""Pydantic v2 schemas for workflow initiation, ledger querying, and step lifecycle tracking."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.security_validation import (
    sanitize_html,
    validate_dynamodb_table_name,
    validate_payload_records,
)


class WorkflowCreateRequest(BaseModel):
    """Payload to initiate an orchestrated cloud migration job."""

    workflow_name: str = Field(
        ..., min_length=3, max_length=255, description="Human-readable workflow title"
    )
    source_type: str = Field(
        ..., description="Data source format (e.g. POSTGRES_SQL_DUMP, CSV, JSON_STREAM)"
    )
    target_dynamodb_table: str = Field(
        ..., min_length=3, max_length=255, description="Destination DynamoDB table name"
    )
    payload_data: list[dict[str, Any]] = Field(
        ..., min_length=1, description="List of source records to extract, transform, and load"
    )
    configuration: dict[str, Any] = Field(
        default_factory=lambda: {"batch_size": 25, "max_retries": 3, "use_multipart": False},
        description="Optional execution tuning parameters",
    )

    @field_validator("workflow_name")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        return sanitize_html(v)

    @field_validator("target_dynamodb_table")
    @classmethod
    def validate_table(cls, v: str) -> str:
        return validate_dynamodb_table_name(v)

    @field_validator("payload_data")
    @classmethod
    def validate_data(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_payload_records(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "workflow_name": "legacy-users-to-dynamodb",
                "source_type": "POSTGRES_SQL_DUMP",
                "target_dynamodb_table": "Users_Production",
                "payload_data": [
                    {"id": "u-101", "name": "Alice Developer", "email": "alice@company.com"},
                    {"id": "u-102", "name": "Bob Architect", "email": "bob@company.com"},
                ],
                "configuration": {"batch_size": 25, "max_retries": 3},
            }
        }
    )


class WorkflowStepResponse(BaseModel):
    """Step execution audit entry reflecting a specific FSM transition."""

    id: str = Field(..., description="Step UUID")
    workflow_id: str = Field(..., description="Parent workflow UUID")
    from_state: str = Field(..., description="Source state before transition")
    to_state: str = Field(..., description="Destination state reached")
    status: str = Field(..., description="Step execution status (e.g. SUCCESS, FAILED)")
    execution_duration_ms: float | None = Field(
        default=None, description="Step duration in milliseconds"
    )
    started_at: datetime = Field(..., description="Step invocation timestamp")
    completed_at: datetime | None = Field(default=None, description="Step completion timestamp")
    error_message: str | None = Field(
        default=None, description="Diagnostic error details if failed"
    )

    model_config = ConfigDict(from_attributes=True)


class WorkflowResponse(BaseModel):
    """Complete workflow entity including execution progress and AWS artifacts."""

    id: str = Field(..., description="Workflow job unique identifier (UUID)")
    workflow_name: str = Field(..., description="Workflow title")
    source_type: str = Field(..., description="Data source format")
    target_dynamodb_table: str = Field(..., description="Destination DynamoDB table")
    current_state: str = Field(..., description="Active FSM lifecycle state")
    records_total: int = Field(..., description="Total records in payload")
    records_processed: int = Field(..., description="Successfully migrated records")
    records_failed: int = Field(..., description="Failed records count")
    progress_percentage: float = Field(..., description="Calculated progress from 0.0 to 100.0%")
    s3_staging_uri: str | None = Field(default=None, description="S3 snapshot URI")
    s3_checksum: str | None = Field(default=None, description="SHA-256 payload checksum")
    configuration: dict[str, Any] = Field(default_factory=dict)
    error_details: dict[str, Any] | None = Field(default=None)
    user_id: str | None = Field(default=None, description="Initiating user UUID")
    created_at: datetime = Field(..., description="Initiation timestamp")
    updated_at: datetime = Field(..., description="Last modification timestamp")
    completed_at: datetime | None = Field(default=None, description="Terminal state timestamp")
    steps: list[WorkflowStepResponse] = Field(
        default_factory=list, description="Ordered audit ledger of state machine steps"
    )

    model_config = ConfigDict(from_attributes=True)


class WorkflowListResponse(BaseModel):
    """Paginated collection of workflows."""

    items: list[WorkflowResponse] = Field(default_factory=list)
    total_items: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total_pages: int = Field(..., ge=0)


class WorkflowRetryRequest(BaseModel):
    """Payload to trigger retry for a failed or stalled workflow."""

    reason: str | None = Field(
        default="Manual operator retry", description="Operational justification for retry"
    )
