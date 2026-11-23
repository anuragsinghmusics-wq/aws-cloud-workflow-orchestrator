"""Task scheduler, exponential backoff with full jitter, and circuit breaker resilience pattern.

Features:
- AWS Exponential Backoff with Full Jitter algorithm.
- Thread-safe 3-state Circuit Breaker (CLOSED, OPEN, HALF_OPEN) to prevent cascading failures.
- Function decorators and context managers for resilient service invocations.
"""

import contextlib
import secrets
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

from src.core.exceptions import CircuitBreakerOpenError
from src.core.logger import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


class CircuitState(str, Enum):
    """States of the resilience circuit breaker."""

    CLOSED = "CLOSED"  # Normal operation: requests pass through
    OPEN = "OPEN"  # Failing state: requests fail immediately without hitting dependency
    HALF_OPEN = "HALF_OPEN"  # Probe state: single test request allowed to check recovery


class CircuitBreaker:
    """Thread-safe circuit breaker protecting external resources (S3, DynamoDB, APIs).

    Transitions:
    - CLOSED -> OPEN: Triggered when consecutive failures >= failure_threshold.
    - OPEN -> HALF_OPEN: Triggered when recovery_timeout seconds have elapsed.
    - HALF_OPEN -> CLOSED: Triggered when a probe call succeeds.
    - HALF_OPEN -> OPEN: Triggered when a probe call fails.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exceptions: tuple = (Exception,),
        ignored_exceptions: tuple = (),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        self.ignored_exceptions = ignored_exceptions

        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_state_change = time.time()
        self._last_failure_time: float | None = None
        self._update_metrics()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state()
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def _update_metrics(self) -> None:
        """Emits circuit breaker state to Prometheus telemetry registry."""
        with contextlib.suppress(Exception):
            from src.core.metrics import metrics_registry

            state_map = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}
            metrics_registry.circuit_breaker_state.set(
                state_map.get(self._state, 0),
                labels={"service": self.name},
            )

    def _evaluate_state(self) -> None:
        """Evaluates whether an OPEN circuit should transition to HALF_OPEN after timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._last_state_change = time.time()
                self._update_metrics()
                logger.info(
                    "Circuit breaker entered HALF_OPEN probe state",
                    extra={"circuit": self.name, "elapsed_seconds": elapsed},
                )

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Executes func wrapped by circuit breaker protection.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and fast-failing.
        """
        with self._lock:
            self._evaluate_state()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN. Call rejected fast to protect downstream service.",
                    details={"circuit": self.name, "failures": self._consecutive_failures},
                )

        # Execute call outside the lock to avoid blocking concurrent threads during I/O
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as exc:
            if self.ignored_exceptions and isinstance(exc, self.ignored_exceptions):
                raise
            if isinstance(exc, self.expected_exceptions):
                self._record_failure(exc)
            raise

    def _record_success(self) -> None:
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info(
                    "Circuit breaker recovered and returned to CLOSED state",
                    extra={"circuit": self.name},
                )
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._last_state_change = time.time()
            self._update_metrics()

    def _record_failure(self, exc: Exception) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_time = time.time()

            if (
                self._state == CircuitState.HALF_OPEN
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                self._update_metrics()
                logger.warning(
                    "Circuit breaker tripped to OPEN state",
                    extra={
                        "circuit": self.name,
                        "consecutive_failures": self._consecutive_failures,
                        "error": str(exc),
                    },
                )

    def reset(self) -> None:
        """Forces manual reset of the circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._last_state_change = time.time()
            self._update_metrics()


# ============================================================================
# Exponential Backoff with Full Jitter
# ============================================================================


def calculate_exponential_backoff(
    attempt: int, base_delay: float = 0.5, max_delay: float = 30.0
) -> float:
    """Implements AWS Exponential Backoff with Full Jitter.

    delay = Uniform(0, min(max_delay, base_delay * 2^attempt))
    """
    temp_delay = min(max_delay, base_delay * (2**attempt))
    sleep_time = secrets.SystemRandom().uniform(0, temp_delay)
    return sleep_time


def execute_with_retry(
    operation: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    circuit_breaker: CircuitBreaker | None = None,
) -> T:
    """Executes a callable with exponential backoff and jitter, optionally gated by a circuit breaker."""
    attempt = 0
    while True:
        try:
            if circuit_breaker:
                return circuit_breaker.call(operation)
            return operation()
        except retryable_exceptions as e:
            attempt += 1
            if attempt > max_retries:
                raise e
            sleep_duration = calculate_exponential_backoff(attempt, base_delay, max_delay)
            time.sleep(sleep_duration)
