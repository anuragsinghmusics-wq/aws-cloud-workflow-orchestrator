"""System health, readiness, and liveness diagnostic probes."""

import time
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.common_schemas import ComponentHealth, HealthResponse
from src.config import get_settings
from src.core.logger import get_logger
from src.database import check_db_health, get_db_session
from src.services.cloudwatch_service import CloudWatchService
from src.services.dynamodb_service import DynamoDBService
from src.services.s3_service import S3Service

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter()


@router.get(
    "/liveness",
    summary="Kubernetes / Docker liveness probe",
)
@router.get(
    "/live",
    include_in_schema=False,
)
async def liveness_probe() -> dict[str, str]:
    """Lightweight, non-blocking check verifying the HTTP application is alive and accepting connections."""
    return {"status": "UP", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


@router.get(
    "/readiness",
    response_model=HealthResponse,
    summary="Comprehensive dependency readiness probe",
)
@router.get(
    "/ready",
    response_model=HealthResponse,
    include_in_schema=False,
)
async def readiness_probe(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> HealthResponse:
    """Probes connectivity to PostgreSQL, S3, DynamoDB, and CloudWatch."""
    components: dict[str, ComponentHealth] = {}
    is_all_healthy = True

    # 1. PostgreSQL Database Probe
    db_start = time.perf_counter()
    try:
        db_healthy = await check_db_health()
        db_latency = (time.perf_counter() - db_start) * 1000
        components["database"] = ComponentHealth(
            status="HEALTHY" if db_healthy else "UNHEALTHY",
            latency_ms=round(db_latency, 2),
            details={"pool_size": settings.DB_POOL_SIZE},
        )
        if not db_healthy:
            is_all_healthy = False
    except Exception as exc:
        is_all_healthy = False
        components["database"] = ComponentHealth(status="UNHEALTHY", details={"error": str(exc)})

    # 2. AWS S3 Probe
    s3_start = time.perf_counter()
    try:
        s3 = S3Service(settings=settings)
        s3_ok = s3.health_check()
        s3_latency = (time.perf_counter() - s3_start) * 1000
        components["s3"] = ComponentHealth(
            status="HEALTHY" if s3_ok else "UNHEALTHY",
            latency_ms=round(s3_latency, 2),
            details={"bucket": settings.S3_BUCKET_NAME},
        )
    except Exception as exc:
        components["s3"] = ComponentHealth(status="DEGRADED", details={"warning": str(exc)})

    # 3. Amazon DynamoDB Probe
    ddb_start = time.perf_counter()
    try:
        ddb = DynamoDBService(settings=settings)
        ddb_ok = ddb.health_check()
        ddb_latency = (time.perf_counter() - ddb_start) * 1000
        components["dynamodb"] = ComponentHealth(
            status="HEALTHY" if ddb_ok else "UNHEALTHY",
            latency_ms=round(ddb_latency, 2),
            details={"table": settings.DYNAMODB_STATE_TABLE},
        )
    except Exception as exc:
        components["dynamodb"] = ComponentHealth(status="DEGRADED", details={"warning": str(exc)})

    # 4. Amazon CloudWatch Probe
    cw_start = time.perf_counter()
    try:
        cw = CloudWatchService(settings=settings)
        cw_ok = cw.health_check()
        cw_latency = (time.perf_counter() - cw_start) * 1000
        components["cloudwatch"] = ComponentHealth(
            status="HEALTHY" if cw_ok else "UNHEALTHY",
            latency_ms=round(cw_latency, 2),
            details={"namespace": settings.CLOUDWATCH_NAMESPACE},
        )
    except Exception as exc:
        components["cloudwatch"] = ComponentHealth(status="DEGRADED", details={"warning": str(exc)})

    overall_status = "HEALTHY" if is_all_healthy else "DEGRADED"
    if not is_all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        components=components,
    )


@router.get(
    "/startup",
    summary="Kubernetes / Docker startup probe",
)
async def startup_probe(response: Response) -> dict[str, Any]:
    """Startup probe verifying core services have initialized."""
    try:
        db_healthy = await check_db_health()
    except Exception:
        db_healthy = False

    if not db_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "STARTING", "database": "UNHEALTHY"}
    return {"status": "READY", "database": "HEALTHY"}


@router.get(
    "",
    response_model=HealthResponse,
    include_in_schema=False,
)
async def default_health_alias(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> HealthResponse:
    """Alias for /readiness."""
    return await readiness_probe(response=response, session=session)
