"""Structured JSON logging and telemetry tracing for the Cloud Workflow Orchestrator.

Provides structured JSON formatters, correlation ID propagation via contextvars,
and automatic sanitization/scrubbing of sensitive credentials (AWS keys, passwords, tokens).
"""

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Context variables for request and workflow correlation across async/thread boundaries
correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
job_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)

# Regex patterns for sensitive key/value redaction
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api_?key|access_?key|authorization|bearer|private_?key)",
    re.IGNORECASE,
)
REDACTED_STRING = "[REDACTED]"


def sanitize_value(key: str, value: Any) -> Any:
    """Recursively redacts sensitive values if the key matches sensitive patterns."""
    if isinstance(key, str) and SENSITIVE_KEY_PATTERN.search(key):
        return REDACTED_STRING

    if isinstance(value, dict):
        return {k: sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(key, item) for item in value]
    return value


class StructuredJsonFormatter(logging.Formatter):
    """Formats standard Python log records into structured, single-line JSON documents."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(
            timespec="milliseconds"
        )

        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "caller": {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Inject context variables
        corr_id = correlation_id_ctx.get()
        if corr_id:
            payload["correlation_id"] = corr_id

        current_job_id = job_id_ctx.get()
        if current_job_id:
            payload["job_id"] = current_job_id

        # Attach extra fields passed via logger.info("...", extra={"key": "val"})
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }
        for attr, val in record.__dict__.items():
            if attr not in standard_attrs and not attr.startswith("_"):
                payload[attr] = sanitize_value(attr, val)

        # Include exception trace if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class TextConsoleFormatter(logging.Formatter):
    """Human-readable colored console formatter for local interactive development."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[
            :-3
        ]

        corr_id = correlation_id_ctx.get()
        corr_str = f" [{corr_id}]" if corr_id else ""
        job_id = job_id_ctx.get()
        job_str = f" [job:{job_id}]" if job_id else ""

        formatted_msg = (
            f"{timestamp} | {color}{record.levelname:<8}{self.RESET} | "
            f"{record.name}:{record.lineno}{corr_str}{job_str} - {record.getMessage()}"
        )
        if record.exc_info:
            formatted_msg += f"\n{self.formatException(record.exc_info)}"
        return formatted_msg


def setup_logging(
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configures the root logging subsystem for the entire application."""
    root_logger = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_format:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(TextConsoleFormatter())

    root_logger.addHandler(handler)

    # Silence overly verbose external loggers
    for noisy in ("botocore", "urllib3", "boto3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Convenience factory to obtain a named logger."""
    return logging.getLogger(name)


class LogContext:
    """Context manager to bind correlation_id and/or job_id to the execution scope."""

    def __init__(
        self,
        correlation_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        self.correlation_id = correlation_id
        self.job_id = job_id
        self._tokens: list = []

    def __enter__(self) -> "LogContext":
        if self.correlation_id is not None:
            self._tokens.append(correlation_id_ctx.set(self.correlation_id))
        if self.job_id is not None:
            self._tokens.append(job_id_ctx.set(self.job_id))
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        for token in reversed(self._tokens):
            if token.var is correlation_id_ctx:
                correlation_id_ctx.reset(token)
            elif token.var is job_id_ctx:
                job_id_ctx.reset(token)
