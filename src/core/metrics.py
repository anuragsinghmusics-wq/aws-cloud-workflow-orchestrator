"""Enterprise Prometheus Metrics Collection, Exposition, and Middleware.

Provides:
- Thread-safe metric primitives (Counter, Gauge, Histogram) compliant with Prometheus text exposition format.
- Pre-defined metrics for HTTP throughput, request duration histograms, workflow transitions,
  data record volume, circuit breaker states, and worker utilization.
- Starlette / FastAPI HTTP request latency tracking middleware.
- Scrapeable endpoint output generator for Prometheus / Grafana agents.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.logger import get_logger

logger = get_logger(__name__)


def _format_labels(labels: dict[str, Any] | None) -> str:
    """Formats label dictionary into Prometheus label syntax: {key="val",key2="val2"}."""
    if not labels:
        return ""
    items = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(items) + "}"


class Metric:
    """Base class for Prometheus metrics with thread-safe label management."""

    def __init__(self, name: str, description: str, metric_type: str) -> None:
        self.name = name
        self.description = description
        self.metric_type = metric_type
        self._lock = threading.Lock()


class Counter(Metric):
    """Monotonically increasing cumulative counter."""

    def __init__(self, name: str, description: str) -> None:
        super().__init__(name, description, "counter")
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def inc(self, amount: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        if amount < 0:
            raise ValueError("Counters can only be incremented monotonically.")
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def get_value(self, labels: dict[str, Any] | None = None) -> float:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            if not self._values:
                lines.append(f"{self.name} 0")
            for key, val in sorted(self._values.items()):
                label_dict = dict(key)
                label_str = _format_labels(label_dict)
                val_str = f"{int(val)}" if val.is_integer() else f"{val:.6f}"
                lines.append(f"{self.name}{label_str} {val_str}")
        return lines


class Gauge(Metric):
    """Numerical metric value that can arbitrarily go up or down."""

    def __init__(self, name: str, description: str) -> None:
        super().__init__(name, description, "gauge")
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def set(self, value: float, labels: dict[str, Any] | None = None) -> None:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - amount

    def get_value(self, labels: dict[str, Any] | None = None) -> float:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            if not self._values:
                lines.append(f"{self.name} 0")
            for key, val in sorted(self._values.items()):
                label_dict = dict(key)
                label_str = _format_labels(label_dict)
                val_str = f"{int(val)}" if val.is_integer() else f"{val:.4f}"
                lines.append(f"{self.name}{label_str} {val_str}")
        return lines


DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Histogram(Metric):
    """Tracks the statistical distribution of observed durations or sizes in buckets."""

    def __init__(
        self,
        name: str,
        description: str,
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, description, "histogram")
        self.buckets = sorted(buckets)
        self._counts: dict[tuple[tuple[str, str], ...], dict[float, int]] = {}
        self._sums: dict[tuple[tuple[str, str], ...], float] = {}
        self._totals: dict[tuple[tuple[str, str], ...], int] = {}

    def observe(self, value: float, labels: dict[str, Any] | None = None) -> None:
        key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            if key not in self._counts:
                self._counts[key] = dict.fromkeys(self.buckets, 0)
                self._sums[key] = 0.0
                self._totals[key] = 0

            self._sums[key] += value
            self._totals[key] += 1
            for b in self.buckets:
                if value <= b:
                    self._counts[key][b] += 1

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for key, bucket_dict in sorted(self._counts.items()):
                label_dict = dict(key)
                for b in self.buckets:
                    b_labels = {**label_dict, "le": str(b)}
                    lines.append(f"{self.name}_bucket{_format_labels(b_labels)} {bucket_dict[b]}")
                inf_labels = {**label_dict, "le": "+Inf"}
                lines.append(f"{self.name}_bucket{_format_labels(inf_labels)} {self._totals[key]}")
                lines.append(f"{self.name}_sum{_format_labels(label_dict)} {self._sums[key]:.6f}")
                lines.append(f"{self.name}_count{_format_labels(label_dict)} {self._totals[key]}")
        return lines


class MetricsRegistry:
    """Singleton registry holding all orchestrator metric collectors."""

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}
        self._lock = threading.Lock()

        # Standard Core Metrics
        self.http_requests_total = self.register(
            Counter(
                "orchestrator_http_requests_total",
                "Total incoming HTTP request count partitioned by method, path, and status code",
            )
        )
        self.http_request_duration_seconds = self.register(
            Histogram(
                "orchestrator_http_request_duration_seconds",
                "HTTP request latency distribution in seconds",
            )
        )
        self.workflows_total = self.register(
            Counter(
                "orchestrator_workflows_total",
                "Total number of workflow jobs submitted to the engine",
            )
        )
        self.workflow_state_gauge = self.register(
            Gauge(
                "orchestrator_workflow_state_gauge",
                "Current number of workflows residing in each state machine phase",
            )
        )
        self.workflow_phase_duration_seconds = self.register(
            Histogram(
                "orchestrator_workflow_phase_duration_seconds",
                "Execution time in seconds spent in each migration pipeline phase",
                buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0),
            )
        )
        self.records_processed_total = self.register(
            Counter(
                "orchestrator_records_processed_total",
                "Total count of successfully transformed and loaded data records",
            )
        )
        self.records_failed_total = self.register(
            Counter(
                "orchestrator_records_failed_total",
                "Total count of rejected or failed data migration records",
            )
        )
        self.circuit_breaker_state = self.register(
            Gauge(
                "orchestrator_circuit_breaker_state",
                "Circuit breaker state per AWS adapter (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
            )
        )
        self.active_workers_gauge = self.register(
            Gauge(
                "orchestrator_active_workers",
                "Estimated concurrent background task execution workers",
            )
        )

    def register(self, metric: Metric) -> Any:
        with self._lock:
            self._metrics[metric.name] = metric
            return metric

    def get_metric(self, name: str) -> Metric | None:
        with self._lock:
            return self._metrics.get(name)

    def generate_exposition(self) -> str:
        """Formats all registered metrics according to Prometheus exposition syntax."""
        output_blocks: list[str] = []
        with self._lock:
            for metric in self._metrics.values():
                rendered = metric.render()
                if rendered:
                    output_blocks.append("\n".join(rendered))
        return "\n\n".join(output_blocks) + "\n"

    def reset_all(self) -> None:
        """Resets all metrics (primarily for test fixture isolation)."""
        with self._lock:
            for metric in self._metrics.values():
                if isinstance(metric, (Counter, Gauge)):
                    metric._values.clear()
                elif isinstance(metric, Histogram):
                    metric._counts.clear()
                    metric._sums.clear()
                    metric._totals.clear()


# Global Singleton Registry
metrics_registry = MetricsRegistry()


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """FastAPI / Starlette middleware that measures request volume, status codes, and latencies."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Avoid instrumenting the /metrics scrape endpoint itself to prevent skew
        if request.url.path in ("/metrics", "/api/v1/metrics/prometheus"):
            return await call_next(request)

        start_time = time.perf_counter()
        method = request.method
        raw_path = request.url.path

        # Normalize high-cardinality paths (UUID / job IDs)
        normalized_path = self._normalize_path(raw_path)

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start_time
            labels = {
                "method": method,
                "path": normalized_path,
                "status": str(status_code),
            }
            metrics_registry.http_requests_total.inc(amount=1.0, labels=labels)
            metrics_registry.http_request_duration_seconds.observe(
                value=duration,
                labels={"method": method, "path": normalized_path},
            )

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalizes dynamic URL parameters to prevent Prometheus label cardinality explosion."""
        segments = path.strip("/").split("/")
        normalized = []
        for segment in segments:
            # Check for UUID / job_id like pattern or long hexadecimal / alphanumeric hash
            if len(segment) >= 20 or (len(segment) == 36 and "-" in segment):
                normalized.append("{id}")
            else:
                normalized.append(segment)
        return "/" + "/".join(normalized) if normalized else "/"
