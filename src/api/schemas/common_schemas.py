"""Shared Pydantic v2 data models for API pagination, health, and error responses."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Standardized RFC 7807 problem details error payload."""

    error: str = Field(..., description="Machine-readable error identifier")
    message: str = Field(..., description="Human-readable error description")
    status_code: int = Field(..., description="HTTP status code")
    retryable: bool = Field(default=False, description="Whether the operation can be retried")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Diagnostic and contextual debug details"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of error occurrence",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "ERR_WORKFLOW_NOT_FOUND",
                "message": "The requested workflow job ID does not exist.",
                "status_code": 404,
                "retryable": False,
                "details": {"job_id": "3bed1630-6783-484d-93c4-138a2ca41529"},
                "timestamp": "2026-11-19T01:45:00.000Z",
            }
        }
    )


class PaginationMeta(BaseModel):
    """Cursor or offset pagination metadata for collection responses."""

    page: int = Field(default=1, ge=1, description="Current page index (1-based)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    total_items: int = Field(..., ge=0, description="Total matching items count")
    total_pages: int = Field(..., ge=0, description="Calculated total pages")


class ComponentHealth(BaseModel):
    """Health check status and connectivity details for an external dependency."""

    status: str = Field(..., description="Service health state: HEALTHY, DEGRADED, or UNHEALTHY")
    latency_ms: float | None = Field(
        default=None, description="Round-trip ping latency in milliseconds"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Diagnostic properties and service metadata"
    )


class HealthResponse(BaseModel):
    """Comprehensive system readiness and liveness probe response."""

    status: str = Field(..., description="Overall system health status")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    version: str = Field(..., description="Active API version")
    environment: str = Field(..., description="Active deployment environment")
    components: dict[str, ComponentHealth] = Field(
        default_factory=dict, description="Health probes for individual subsystems"
    )
