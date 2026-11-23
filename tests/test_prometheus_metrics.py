"""Unit and integration tests for Prometheus metrics engine, exposition, and ASGI middleware."""

import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from src.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    PrometheusMetricsMiddleware,
    metrics_registry,
)
from src.database import get_db_session
from src.main import app


class TestPrometheusMetricsEngine(unittest.TestCase):
    """Verifies thread-safe metric primitives and standard Prometheus format generation."""

    def setUp(self):
        self.registry = MetricsRegistry()

    def test_counter_monotonic_increment(self):
        c = Counter("test_counter_total", "Test counter description")
        self.assertEqual(c.get_value(), 0.0)

        c.inc(1.0)
        self.assertEqual(c.get_value(), 1.0)

        c.inc(2.5, labels={"method": "POST", "status": "200"})
        self.assertEqual(c.get_value(labels={"method": "POST", "status": "200"}), 2.5)

        with self.assertRaises(ValueError):
            c.inc(-1.0)

        rendered = c.render()
        text = "\n".join(rendered)
        self.assertIn("# HELP test_counter_total Test counter description", text)
        self.assertIn("# TYPE test_counter_total counter", text)
        self.assertIn('test_counter_total{method="POST",status="200"} 2.500000', text)

    def test_gauge_arbitrary_adjustments(self):
        g = Gauge("test_gauge_val", "Test gauge description")
        self.assertEqual(g.get_value(), 0.0)

        g.set(42.0)
        self.assertEqual(g.get_value(), 42.0)

        g.inc(5.0)
        self.assertEqual(g.get_value(), 47.0)

        g.dec(12.0)
        self.assertEqual(g.get_value(), 35.0)

        rendered = g.render()
        text = "\n".join(rendered)
        self.assertIn("# HELP test_gauge_val Test gauge description", text)
        self.assertIn("# TYPE test_gauge_val gauge", text)
        self.assertIn("test_gauge_val 35", text)

    def test_histogram_bucket_observations(self):
        h = Histogram(
            "test_histogram_latency",
            "Latency distribution",
            buckets=(0.01, 0.05, 0.1, 1.0),
        )
        h.observe(0.005, labels={"route": "/api"})
        h.observe(0.02, labels={"route": "/api"})
        h.observe(0.5, labels={"route": "/api"})

        rendered = h.render()
        text = "\n".join(rendered)
        self.assertIn("# HELP test_histogram_latency Latency distribution", text)
        self.assertIn("# TYPE test_histogram_latency histogram", text)
        self.assertIn('test_histogram_latency_bucket{le="0.01",route="/api"} 1', text)
        self.assertIn('test_histogram_latency_bucket{le="0.05",route="/api"} 2', text)
        self.assertIn('test_histogram_latency_bucket{le="0.1",route="/api"} 2', text)
        self.assertIn('test_histogram_latency_bucket{le="1.0",route="/api"} 3', text)
        self.assertIn('test_histogram_latency_bucket{le="+Inf",route="/api"} 3', text)
        self.assertIn('test_histogram_latency_count{route="/api"} 3', text)

    def test_registry_exposition_and_reset(self):
        reg = MetricsRegistry()
        reg.workflows_total.inc(3.0)
        reg.workflow_state_gauge.set(2.0, labels={"state": "EXTRACTING"})

        expo = reg.generate_exposition()
        self.assertIn("orchestrator_workflows_total 3", expo)
        self.assertIn('orchestrator_workflow_state_gauge{state="EXTRACTING"} 2', expo)

        reg.reset_all()
        empty_expo = reg.generate_exposition()
        self.assertIn("orchestrator_workflows_total 0", empty_expo)

    def test_middleware_path_normalization(self):
        self.assertEqual(
            PrometheusMetricsMiddleware._normalize_path(
                "/api/v1/workflows/wf-550e8400-e29b-41d4-a716-446655440000"
            ),
            "/api/v1/workflows/{id}",
        )
        self.assertEqual(
            PrometheusMetricsMiddleware._normalize_path("/api/v1/health/live"),
            "/api/v1/health/live",
        )
        self.assertEqual(
            PrometheusMetricsMiddleware._normalize_path("/"),
            "/",
        )


class TestPrometheusHTTPEndpoints(unittest.TestCase):
    """Verifies that the /metrics root and /api/v1/metrics/prometheus routes serve scrapeable text."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()

        async def override_db():
            yield self.mock_session

        app.dependency_overrides[get_db_session] = override_db
        metrics_registry.reset_all()

    def tearDown(self):
        app.dependency_overrides.clear()
        metrics_registry.reset_all()

    def test_root_metrics_scrape_endpoint(self):
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers["content-type"])
        body = res.text
        self.assertIn("orchestrator_http_requests_total", body)
        self.assertIn("orchestrator_workflows_total", body)

    def test_api_v1_prometheus_alias_endpoint(self):
        res = self.client.get("/api/v1/metrics/prometheus")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers["content-type"])
        self.assertIn("orchestrator_circuit_breaker_state", res.text)

    def test_middleware_records_live_traffic(self):
        # Fire health check request
        res = self.client.get("/api/v1/health/live")
        self.assertEqual(res.status_code, 200)

        # Scrape metrics and verify count
        metrics_res = self.client.get("/metrics")
        body = metrics_res.text
        self.assertIn(
            'orchestrator_http_requests_total{method="GET",path="/api/v1/health/live",status="200"}',
            body,
        )


if __name__ == "__main__":
    unittest.main()
