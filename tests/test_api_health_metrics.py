"""Integration tests for health probes, liveness, and telemetry metrics endpoints."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.core.security import get_current_active_user
from src.database import get_db_session
from src.main import app


class TestHealthAndMetricsAPI(unittest.TestCase):
    """Verifies that diagnostic health checks and telemetry metrics endpoints respond correctly."""

    def setUp(self):
        self.client = TestClient(app)

    def test_liveness_probe_returns_up(self):
        response = self.client.get("/api/v1/health/liveness")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "UP")
        self.assertIn("timestamp", data)

    def test_root_endpoint_metadata(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("project", data)
        self.assertIn("version", data)
        self.assertEqual(data["documentation"], "/docs")

    @patch("src.api.v1.health.check_db_health")
    @patch("src.api.v1.health.S3Service")
    @patch("src.api.v1.health.DynamoDBService")
    @patch("src.api.v1.health.CloudWatchService")
    def test_readiness_probe_healthy(self, mock_cw, mock_ddb, mock_s3, mock_db_health):
        mock_db_health.return_value = True
        mock_s3.return_value.health_check.return_value = True
        mock_ddb.return_value.health_check.return_value = True
        mock_cw.return_value.health_check.return_value = True

        response = self.client.get("/api/v1/health/readiness")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "HEALTHY")
        self.assertIn("database", data["components"])
        self.assertIn("s3", data["components"])
        self.assertIn("dynamodb", data["components"])
        self.assertIn("cloudwatch", data["components"])

    @patch("src.api.v1.health.check_db_health")
    def test_readiness_probe_degraded_when_db_fails(self, mock_db_health):
        mock_db_health.return_value = False

        response = self.client.get("/api/v1/health/readiness")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "DEGRADED")
        self.assertEqual(data["components"]["database"]["status"], "UNHEALTHY")

    def test_metrics_json_export(self):
        mock_session = AsyncMock()

        async def override_db():
            yield mock_session

        # Mock state counts query: [("COMPLETED", 5), ("FAILED", 1)]
        mock_state_res = MagicMock()
        mock_state_res.all.return_value = [("COMPLETED", 5), ("FAILED", 1)]

        # Mock vol query: total=1000, processed=950, failed=50
        mock_vol_res = MagicMock()
        mock_vol_res.one.return_value = (1000, 950, 50)

        mock_session.execute.side_effect = [mock_state_res, mock_vol_res]

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: None
        try:
            response = self.client.get("/api/v1/metrics", headers={"Accept": "application/json"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("workflows", data)
            self.assertEqual(data["workflows"]["total"], 6)
            self.assertIn("records", data)
            self.assertEqual(data["records"]["total_submitted"], 1000)
            self.assertIn("system", data)
            self.assertIn("cpu_percent", data["system"])
        finally:
            app.dependency_overrides.clear()

    def test_metrics_prometheus_text_export(self):
        mock_session = AsyncMock()

        async def override_db():
            yield mock_session

        mock_state_res = MagicMock()
        mock_state_res.all.return_value = [("COMPLETED", 2)]

        mock_vol_res = MagicMock()
        mock_vol_res.one.return_value = (50, 50, 0)

        mock_session.execute.side_effect = [mock_state_res, mock_vol_res]

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: None
        try:
            response = self.client.get("/api/v1/metrics", headers={"Accept": "text/plain"})
            self.assertEqual(response.status_code, 200)
            text_body = response.text
            self.assertIn("orchestrator_workflows_total", text_body)
            self.assertIn("orchestrator_records_processed_total", text_body)
            self.assertIn("orchestrator_cpu_usage_percent", text_body)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
