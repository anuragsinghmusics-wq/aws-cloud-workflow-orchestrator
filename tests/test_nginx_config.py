"""Unit tests verifying Nginx, Prometheus, Grafana, and Docker Compose configurations."""

import json
import unittest
from pathlib import Path


class TestProductionInfrastructureConfigs(unittest.TestCase):
    """Verifies syntactic and structural integrity of production infrastructure assets."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_nginx_main_conf_structure(self):
        nginx_conf = self.repo_root / "docker" / "nginx" / "nginx.conf"
        self.assertTrue(nginx_conf.exists(), "docker/nginx/nginx.conf must exist")

        content = nginx_conf.read_text(encoding="utf-8")
        self.assertIn("worker_processes auto;", content)
        self.assertIn("limit_req_zone", content)
        self.assertIn("auth_strict_limit", content)
        self.assertIn("gzip on;", content)
        self.assertIn("log_format json_analytics", content)

    def test_nginx_orchestrator_virtual_host_conf(self):
        vhost_conf = self.repo_root / "docker" / "nginx" / "conf.d" / "orchestrator.conf"
        self.assertTrue(vhost_conf.exists(), "docker/nginx/conf.d/orchestrator.conf must exist")

        content = vhost_conf.read_text(encoding="utf-8")
        self.assertIn("upstream fastapi_cluster", content)
        self.assertIn("map $http_upgrade $connection_upgrade", content)
        self.assertIn('X-Frame-Options "DENY"', content)
        self.assertIn('X-Content-Type-Options "nosniff"', content)
        self.assertIn("location /api/v1/auth/login", content)
        self.assertIn("location /api/", content)
        self.assertIn("location ~ ^/(?:api/v1/)?ws/", content)
        self.assertIn("location /metrics", content)
        self.assertIn("location /health/", content)

    def test_prometheus_scrape_config(self):
        prom_conf = self.repo_root / "docker" / "prometheus" / "prometheus.yml"
        self.assertTrue(prom_conf.exists(), "docker/prometheus/prometheus.yml must exist")

        content = prom_conf.read_text(encoding="utf-8")
        self.assertIn("scrape_interval: 5s", content)
        self.assertIn("orchestrator-api", content)
        self.assertIn("web:8000", content)

    def test_grafana_dashboard_json_validity(self):
        dashboard_file = (
            self.repo_root / "docker" / "grafana" / "dashboards" / "orchestrator_overview.json"
        )
        self.assertTrue(dashboard_file.exists(), "Grafana dashboard JSON must exist")

        data = json.loads(dashboard_file.read_text(encoding="utf-8"))
        self.assertEqual(
            data.get("title"), "Cloud Workflow Orchestrator - Production Mission Control"
        )
        self.assertGreater(len(data.get("panels", [])), 5)

        # Verify panels have targets
        panel_titles = [p.get("title", "") for p in data["panels"] if p.get("title")]
        self.assertIn("Total Migrations Submitted", panel_titles)
        self.assertIn("Records Successfully Migrated", panel_titles)
        self.assertIn("API Request Latency Percentiles (p50, p95, p99)", panel_titles)

    def test_production_docker_compose_services(self):
        compose_file = self.repo_root / "docker" / "docker-compose.prod.yml"
        self.assertTrue(compose_file.exists(), "docker-compose.prod.yml must exist")

        content = compose_file.read_text(encoding="utf-8")
        required_services = [
            "nginx:",
            "web:",
            "celery-worker:",
            "celery-beat:",
            "flower:",
            "postgres:",
            "redis:",
            "localstack:",
            "prometheus:",
            "grafana:",
        ]
        for service in required_services:
            self.assertIn(
                service, content, f"Service {service} must be declared in docker-compose.prod.yml"
            )


if __name__ == "__main__":
    unittest.main()
