"""FastAPI application entry point for the Cloud-Native Workflow Orchestrator.

Configures enterprise ASGI middleware (CORS, correlation ID tracing, structured request logging),
global RFC 7807 domain exception handling, WebSocket streaming, and REST API v1 routing.
"""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from src.api.v1 import api_v1_router
from src.api.websocket_manager import ws_manager
from src.config import get_settings
from src.core.exceptions import OrchestratorError
from src.core.logger import correlation_id_ctx, get_logger
from src.core.metrics import PrometheusMetricsMiddleware, metrics_registry
from src.core.security_headers import SecurityHeadersMiddleware
from src.core.shutdown import shutdown_manager

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager handling application startup and shutdown events."""
    logger.info(
        "Starting Cloud Workflow Orchestrator service",
        extra={
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "use_localstack": settings.USE_LOCALSTACK,
            "api_prefix": settings.API_V1_PREFIX,
        },
    )
    yield
    logger.info("Shutting down Cloud Workflow Orchestrator service")
    await shutdown_manager.initiate_shutdown()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Production-grade, cloud-native automated migration and workflow orchestration engine. "
        "Provides state-machine-driven data migration across AWS S3 and DynamoDB with real-time "
        "telemetry, JWT/API-key authentication, and WebSocket live updates."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ----------------------------------------------------------------------------
# CORS Middleware
# ----------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "Content-Disposition"],
)

# ----------------------------------------------------------------------------
# Prometheus Metrics Middleware
# ----------------------------------------------------------------------------
app.add_middleware(PrometheusMetricsMiddleware)

# ----------------------------------------------------------------------------
# OWASP Security Headers Middleware
# ----------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)


# ----------------------------------------------------------------------------
# Request Correlation ID & Access Logging Middleware
# ----------------------------------------------------------------------------
@app.middleware("http")
async def correlation_and_access_middleware(request: Request, call_next):
    """Generates or propagates X-Correlation-ID, binds it to contextvars, and records latency."""
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    token = correlation_id_ctx.set(correlation_id)

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Correlation-ID"] = correlation_id

        logger.info(
            f"{request.method} {request.url.path} HTTP/{request.scope.get('http_version', '1.1')} "
            f"-> {response.status_code} ({duration_ms}ms)",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )
        return response
    finally:
        correlation_id_ctx.reset(token)


# ----------------------------------------------------------------------------
# Global Domain Exception Handler
# ----------------------------------------------------------------------------
@app.exception_handler(OrchestratorError)
async def orchestrator_error_handler(request: Request, exc: OrchestratorError):
    """Maps domain-specific exceptions to standardized JSON responses."""
    logger.warning(
        f"Domain error handled on {request.method} {request.url.path}: {exc.message}",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.http_status_code,
            "retryable": exc.retryable,
            "details": exc.details,
        },
    )
    return JSONResponse(
        status_code=exc.http_status_code,
        content=exc.to_dict(),
        headers={"X-Correlation-ID": correlation_id_ctx.get() or "unknown"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catches unhandled errors, ensuring no stack traces leak to callers."""
    logger.error(
        f"Unhandled server error on {request.method} {request.url.path}: {exc}",
        extra={"error": str(exc), "path": request.url.path},
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "ERR_INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred. Please contact system administrator.",
            "status_code": 500,
            "retryable": False,
        },
        headers={"X-Correlation-ID": correlation_id_ctx.get() or "unknown"},
    )


# ----------------------------------------------------------------------------
# WebSocket Real-Time Status Streaming
# ----------------------------------------------------------------------------
@app.websocket(f"{settings.API_V1_PREFIX}/ws/workflows/{{job_id}}")
@app.websocket("/ws/workflows/{job_id}")
async def websocket_workflow_stream(websocket: WebSocket, job_id: str):
    """Subscribes a client to real-time state machine progress updates for a workflow."""
    await ws_manager.connect(websocket, job_id)
    try:
        # Send initial confirmation event
        await websocket.send_json(
            {
                "event": "SUBSCRIBED",
                "job_id": job_id,
                "message": f"Successfully subscribed to live updates for workflow '{job_id}'.",
            }
        )
        # Keep connection open and handle incoming client heartbeats/pings
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, job_id)
    except Exception as exc:
        logger.warning(
            "WebSocket streaming error",
            extra={"job_id": job_id, "error": str(exc)},
        )
        ws_manager.disconnect(websocket, job_id)


# ----------------------------------------------------------------------------
# Include REST API Routers
# ----------------------------------------------------------------------------
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics_endpoint():
    """Exposes real-time Prometheus metrics for scrapers (Prometheus, Grafana Agent, Datadog)."""
    exposition = metrics_registry.generate_exposition()
    return Response(
        content=exposition,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Root endpoint providing quick system overview and link to documentation."""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "documentation": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
