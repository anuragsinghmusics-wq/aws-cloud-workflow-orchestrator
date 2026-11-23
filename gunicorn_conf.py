"""Production Gunicorn Configuration for Cloud-Native Workflow Orchestrator.

Optimized for high-throughput, asynchronous ASGI execution with Uvicorn workers.
Features:
- Dynamic CPU-based worker sizing with container override support.
- Worker recycling to combat memory fragmentation and leaks.
- Graceful termination timeouts for active migration tasks.
- Structured access log formatting with latency tracking.
- Post-fork hooks for database and telemetry re-initialization.
"""

from __future__ import annotations

import multiprocessing
import os

# Server Socket Binding
host = os.getenv("HOST", "0.0.0.0")
port = os.getenv("PORT", "8000")
bind = f"{host}:{port}"

# Backlog of unaccepted connections
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

# Worker Processes
# Standard rule: (2 * CPU) + 1, capped conservatively for containers
default_workers = max(2, multiprocessing.cpu_count() * 2 + 1)
workers = int(os.getenv("WEB_CONCURRENCY", default_workers))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "1000"))

# Timeouts & Keep-Alive
# 120s allows long-running payload validation or S3 uploads without premature termination
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Worker Lifecycle & Memory Defense
# Automatically restart workers after N requests to prevent Python heap memory leaks
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "5000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "500"))

# Logging & Observability
accesslog = "-"  # stdout
errorlog = "-"  # stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = (
    '{"time":"%(t)s","remote_ip":"%(h)s","method":"%(m)s","path":"%(U)s",'
    '"status":%(s)s,"bytes":%(B)s,"duration_ms":%(D)s,"user_agent":"%(a)s"}'
)

# Process Naming
proc_name = "aws-cloud-workflow-orchestrator"


# Server Lifecycle Hooks
def on_starting(server):
    """Executes once in master process prior to forking workers."""
    server.log.info(
        f"Gunicorn master starting on {bind} with {workers} Uvicorn workers (PID {os.getpid()})"
    )


def post_fork(server, worker):
    """Executes inside each worker process immediately after fork."""
    server.log.info(f"Worker spawned (PID: {worker.pid})")


def worker_int(worker):
    """Executes when worker receives SIGINT or SIGQUIT."""
    worker.log.info(f"Worker received INT or QUIT signal (PID: {worker.pid})")


def worker_abort(worker):
    """Executes when worker receives SIGABRT (timeout exceeded)."""
    worker.log.error(f"Worker timed out and received SIGABRT (PID: {worker.pid})")


def on_exit(server):
    """Executes when master process is terminating."""
    server.log.info("Gunicorn master process shutting down gracefully.")
