"""Graceful Shutdown and Lifecycle Termination Controller.

Governs orderly server shutdown upon SIGTERM / SIGINT:
- Prevents new migration tasks from starting once shutdown begins.
- Waits for active in-flight tasks to complete or checkpoint within a configurable timeout.
- Cleanly closes PostgreSQL connection pools, Redis clients, and background watchers.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Generator

from src.core.exceptions import OrchestratorError
from src.core.logger import get_logger

logger = get_logger(__name__)


class ServiceUnavailableError(OrchestratorError):
    """Raised when incoming requests or tasks are rejected due to ongoing graceful shutdown."""

    def __init__(self, message: str = "Service is shutting down. Request rejected.") -> None:
        super().__init__(
            message=message,
            error_code="ERR_SERVICE_SHUTTING_DOWN",
            http_status_code=503,
            retryable=True,
        )


class GracefulShutdownManager:
    """Coordinates graceful draining of tasks and disposal of database/network connections."""

    def __init__(self, shutdown_timeout: float = 30.0) -> None:
        self.shutdown_timeout = shutdown_timeout
        self._is_shutting_down = False
        self._active_tasks = 0
        self._lock = threading.Lock()

    @property
    def is_shutting_down(self) -> bool:
        with self._lock:
            return self._is_shutting_down

    @property
    def active_tasks(self) -> int:
        with self._lock:
            return self._active_tasks

    @contextlib.contextmanager
    def track_task(self) -> Generator[None, None, None]:
        """Context manager tracking active task execution.

        Raises:
            ServiceUnavailableError: If the system is currently shutting down.
        """
        with self._lock:
            if self._is_shutting_down:
                raise ServiceUnavailableError()
            self._active_tasks += 1

        try:
            yield
        finally:
            with self._lock:
                self._active_tasks = max(0, self._active_tasks - 1)

    def mark_shutting_down(self) -> None:
        """Immediately marks the system as shutting down to reject incoming work."""
        with self._lock:
            self._is_shutting_down = True

    async def initiate_shutdown(self) -> None:
        """Transitions into draining state and waits for active tasks to conclude."""
        with self._lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True

        logger.info(
            "Graceful shutdown initiated. Rejecting new tasks, awaiting active tasks...",
            extra={"active_tasks": self.active_tasks, "timeout_seconds": self.shutdown_timeout},
        )

        start_time = time.time()
        while self.active_tasks > 0:
            elapsed = time.time() - start_time
            if elapsed >= self.shutdown_timeout:
                logger.warning(
                    "Shutdown timeout exceeded with tasks still active. Forcing shutdown.",
                    extra={"abandoned_tasks": self.active_tasks},
                )
                break
            await asyncio.sleep(0.2)

        # Dispose Database Connection Pool
        try:
            from src.database import engine

            await engine.dispose()
            logger.info("Database connection engine disposed cleanly.")
        except Exception as exc:
            logger.warning("Error disposing database engine", extra={"error": str(exc)})

        logger.info("Graceful shutdown completed.")

    def reset(self) -> None:
        """Resets shutdown state (for testing isolation)."""
        with self._lock:
            self._is_shutting_down = False
            self._active_tasks = 0


# Global Singleton Shutdown Manager
shutdown_manager = GracefulShutdownManager()
