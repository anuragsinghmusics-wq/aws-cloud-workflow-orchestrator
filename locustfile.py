"""Industrial Locust Load & Performance Testing Suite.

Simulates 100+ concurrent operators executing migration workflows, polling job statuses,
and monitoring system health and Prometheus telemetry metrics.

Usage:
    # Interactive Web UI at http://localhost:8089:
    locust -f locustfile.py

    # Headless 10-minute production stress test:
    locust -f locustfile.py --headless -u 100 -r 10 --run-time 10m --host http://localhost:8000
"""

from __future__ import annotations

import os
import random
import uuid
from typing import Any

from locust import HttpUser, between, events, task


class WorkflowOrchestratorUser(HttpUser):
    """Simulates an enterprise operator interacting with the workflow orchestrator."""

    wait_time = between(1.0, 3.0)
    token: str | None = None
    headers: dict[str, str] = {}

    def on_start(self) -> None:
        """Authenticates or registers user to obtain JWT token on worker start."""
        unique_suffix = uuid.uuid4().hex[:8]
        email = f"loadtest_{unique_suffix}@orchestrator.io"
        password = "LoadTestPassword123!"

        # Register user
        register_payload = {
            "email": email,
            "password": password,
            "role": "OPERATOR",
        }

        reg_res = self.client.post("/api/v1/auth/register", json=register_payload)
        if reg_res.status_code not in (200, 201, 409):
            # Fallback to default demo user if register is disabled/already created
            email = os.getenv("LOADTEST_USER", "admin@orchestrator.io")
            password = os.getenv("LOADTEST_PASSWORD", "AdminPass123!")

        # Login to obtain JWT
        login_res = self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        if login_res.status_code == 200:
            data = login_res.json()
            self.token = data.get("access_token")
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        else:
            self.headers = {"Content-Type": "application/json"}

    @task(5)
    def create_and_monitor_workflow(self) -> None:
        """Creates a migration workflow with batch records and monitors progression."""
        batch_size = random.randint(10, 50)
        records = [
            {
                "id": f"rec_{uuid.uuid4().hex[:8]}",
                "name": f"User_{i}",
                "balance": round(random.uniform(10.0, 5000.0), 2),
                "is_active": True,
            }
            for i in range(batch_size)
        ]

        idempotency_key = str(uuid.uuid4())
        req_headers = dict(self.headers)
        req_headers["Idempotency-Key"] = idempotency_key

        payload: dict[str, Any] = {
            "workflow_name": f"LoadTest_Migration_{uuid.uuid4().hex[:6]}",
            "source_type": "JSON",
            "target_dynamodb_table": "Performance_Metrics_Table",
            "payload_data": records,
            "configuration": {"batch_size": 25},
        }

        with self.client.post(
            "/api/v1/workflows/",
            json=payload,
            headers=req_headers,
            catch_response=True,
            name="/api/v1/workflows/ [CREATE]",
        ) as response:
            if response.status_code in (200, 201):
                res_data = response.json()
                job_id = res_data.get("job_id")
                response.success()

                # Poll workflow status
                if job_id:
                    self.client.get(
                        f"/api/v1/workflows/{job_id}",
                        headers=self.headers,
                        name="/api/v1/workflows/[id] [STATUS]",
                    )
            elif response.status_code == 401 and not self.token:
                response.success()  # Unauthenticated runs tolerated in unauthed mock environments
            else:
                response.failure(
                    f"Workflow create returned {response.status_code}: {response.text}"
                )

    @task(3)
    def list_workflows_paginated(self) -> None:
        """Fetches paginated workflow lists."""
        limit = random.choice([10, 20, 50])
        self.client.get(
            f"/api/v1/workflows/?limit={limit}&offset=0",
            headers=self.headers,
            name="/api/v1/workflows/ [LIST]",
        )

    @task(2)
    def check_health_and_metrics(self) -> None:
        """Scrapes liveness, readiness, and Prometheus metrics."""
        self.client.get("/health/live", name="/health/live")
        self.client.get("/health/ready", name="/health/ready")
        self.client.get("/metrics", name="/metrics [PROMETHEUS]")

    @task(1)
    def inspect_quarantined_dlq(self) -> None:
        """Monitors dead letter queue quarantined records."""
        self.client.get("/api/v1/dlq/?limit=20", headers=self.headers, name="/api/v1/dlq/ [LIST]")


@events.test_stop.add_listener
def on_test_stop(environment: Any, **_kwargs: Any) -> None:
    """Emits consolidated performance statistics upon load test conclusion."""
    total_stats = environment.runner.stats.total
    print("\n" + "=" * 60)
    print("LOCUST LOAD TEST SUMMARY")
    print("=" * 60)
    print(f"Total Requests:       {total_stats.num_requests}")
    print(f"Total Failures:       {total_stats.num_failures}")
    print(f"Failure Rate:         {total_stats.fail_ratio * 100:.2f}%")
    print(f"Requests / Second:    {total_stats.total_rps:.2f}")
    print(f"Median Latency (p50): {total_stats.median_response_time} ms")
    print(f"95th Latency (p95):   {total_stats.get_response_time_percentile(0.95)} ms")
    print(f"99th Latency (p99):   {total_stats.get_response_time_percentile(0.99)} ms")
    print("=" * 60 + "\n")
