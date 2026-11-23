"""Telemetry, operational statistics, and Prometheus metrics aggregation routes."""

from typing import Any

import psutil
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.metrics import metrics_registry
from src.core.security import get_current_active_user
from src.database import get_db_session
from src.models.user import User
from src.models.workflow import Workflow

settings = get_settings()
router = APIRouter()


@router.get(
    "",
    summary="Get aggregated operational and workflow execution metrics",
)
async def get_metrics(
    accept: str | None = Header(default="application/json"),
    current_user: User | None = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """Returns workflow KPIs, state distribution, records migrated, and host resource utilization."""
    # 1. Total and state distribution
    state_stmt = select(Workflow.current_state, func.count(Workflow.id)).group_by(
        Workflow.current_state
    )
    state_res = await session.execute(state_stmt)
    state_counts = dict(state_res.all())

    total_workflows = sum(state_counts.values())
    completed_count = state_counts.get("COMPLETED", 0)
    failed_count = state_counts.get("FAILED", 0)
    terminal_count = completed_count + failed_count
    success_rate = (
        round((completed_count / terminal_count) * 100.0, 2) if terminal_count > 0 else 100.0
    )

    # 2. Record volume aggregations
    vol_stmt = select(
        func.sum(Workflow.records_total),
        func.sum(Workflow.records_processed),
        func.sum(Workflow.records_failed),
    )
    vol_res = await session.execute(vol_stmt)
    total_records, total_processed, total_failed = vol_res.one()

    # 3. Host system metrics via psutil
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()

    metrics_payload = {
        "workflows": {
            "total": total_workflows,
            "by_state": state_counts,
            "success_rate_percent": success_rate,
        },
        "records": {
            "total_submitted": int(total_records or 0),
            "total_processed": int(total_processed or 0),
            "total_failed": int(total_failed or 0),
        },
        "system": {
            "cpu_percent": cpu_percent,
            "memory_used_mb": round(mem.used / (1024 * 1024), 2),
            "memory_percent": mem.percent,
            "concurrency_limit": settings.WORKER_CONCURRENCY,
        },
    }

    # If Prometheus client requests plain text format
    if accept and "text/plain" in accept:
        lines = [
            "# HELP orchestrator_workflows_total Total workflow jobs registered",
            "# TYPE orchestrator_workflows_total counter",
            f"orchestrator_workflows_total {total_workflows}",
            "# HELP orchestrator_workflows_success_rate Workflow completion success percentage",
            "# TYPE orchestrator_workflows_success_rate gauge",
            f"orchestrator_workflows_success_rate {success_rate}",
            "# HELP orchestrator_records_processed_total Successfully migrated data records",
            "# TYPE orchestrator_records_processed_total counter",
            f"orchestrator_records_processed_total {total_processed or 0}",
            "# HELP orchestrator_records_failed_total Failed records",
            "# TYPE orchestrator_records_failed_total counter",
            f"orchestrator_records_failed_total {total_failed or 0}",
            "# HELP orchestrator_cpu_usage_percent CPU utilization percentage",
            "# TYPE orchestrator_cpu_usage_percent gauge",
            f"orchestrator_cpu_usage_percent {cpu_percent}",
        ]
        for state, count in state_counts.items():
            lines.append(f'orchestrator_workflows_by_state{{state="{state}"}} {count}')
        return Response(content="\n".join(lines) + "\n", media_type="text/plain")

    return metrics_payload


@router.get(
    "/prometheus",
    summary="Get raw Prometheus text exposition metrics",
)
async def get_prometheus_metrics() -> Response:
    """Returns application metrics formatted according to Prometheus exposition syntax."""
    exposition = metrics_registry.generate_exposition()
    return Response(
        content=exposition,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
