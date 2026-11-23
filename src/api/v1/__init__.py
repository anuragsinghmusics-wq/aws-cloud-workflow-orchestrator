"""API version 1 package router aggregation."""

from fastapi import APIRouter

from src.api.v1.auth import router as auth_router
from src.api.v1.dlq import router as dlq_router
from src.api.v1.export import router as export_router
from src.api.v1.health import router as health_router
from src.api.v1.metrics import router as metrics_router
from src.api.v1.schedules import router as schedules_router
from src.api.v1.templates import router as templates_router
from src.api.v1.webhooks import router as webhooks_router
from src.api.v1.workflows import router as workflows_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication & Identity"])
api_v1_router.include_router(
    workflows_router, prefix="/workflows", tags=["Workflows & Orchestration"]
)
api_v1_router.include_router(schedules_router, prefix="/schedules", tags=["Workflow Schedules"])
api_v1_router.include_router(webhooks_router, prefix="/webhooks", tags=["Webhook Subscriptions"])
api_v1_router.include_router(export_router, prefix="/export", tags=["Data Export & Artifacts"])
api_v1_router.include_router(templates_router, tags=["Templates & Bulk Operations"])
api_v1_router.include_router(dlq_router, prefix="/dlq", tags=["Dead-Letter Queue & Quarantine"])
api_v1_router.include_router(health_router, prefix="/health", tags=["Health & Diagnostics"])
api_v1_router.include_router(metrics_router, prefix="/metrics", tags=["Telemetry & Metrics"])

__all__ = ["api_v1_router"]
