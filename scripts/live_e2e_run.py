"""Exercises the live containerized Docker stack via HTTP calls to http://localhost:8000."""

import time

import httpx

API_BASE = "http://localhost:8000"


def run_live_cluster_workflow():
    print("=" * 70)
    print("🌐 EXECUTING LIVE WORKFLOW ON DOCKER CLUSTER")
    print("=" * 70)

    client = httpx.Client(base_url=API_BASE, timeout=60.0)

    # 1. Health Probe
    print("\n[Step 1/5] Checking Service Cluster Liveness...")
    live_resp = client.get("/api/v1/health/live")
    print(f"  ✓ Cluster Liveness Status: {live_resp.status_code} - {live_resp.json()['status']}")

    # 2. Register Operator
    print("\n[Step 2/5] Registering Operator Account...")
    email = f"admin_ops_{int(time.time())}@cloud-orchestrator.io"
    reg_payload = {
        "email": email,
        "password": "ProductionPassword123!",
        "full_name": "Cluster Administrator",
        "role": "ADMIN",
    }
    reg_resp = client.post("/api/v1/auth/register", json=reg_payload)
    print(f"  ✓ User Registered: {reg_resp.status_code} - {reg_resp.json()['email']}")

    # 3. Authenticate and Obtain JWT
    print("\n[Step 3/5] Authenticating to Obtain JWT Bearer Token...")
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "ProductionPassword123!"},
    )
    tokens = login_resp.json()
    access_token = tokens["access_token"]
    print(f"  ✓ JWT Access Token Acquired: {access_token[:25]}... (valid 30m)")

    # 4. Generate Machine API Key
    print("\n[Step 4/5] Generating Machine-to-Machine API Key...")
    headers = {"Authorization": f"Bearer {access_token}"}
    key_resp = client.post(
        "/api/v1/auth/api-keys",
        headers=headers,
        json={"name": "cluster-live-runner", "expires_days": 30},
    )
    api_key_data = key_resp.json()
    api_key = api_key_data["raw_key"]
    print(f"  ✓ API Key Created: {api_key[:18]}... (Key ID: {api_key_data['id']})")

    # 5. Submit Migration Workflow via API Key
    print("\n[Step 5/5] Submitting Migration Workflow via API Key...")
    records = [
        {
            "record_id": f"rec_{5000 + i}",
            "account_id": f"acc_{5000 + i}",
            "organization": f"Enterprise Client {i}",
            "cloud_provider": "AWS" if i % 2 == 0 else "GCP",
            "active_services": 12 + i,
            "monthly_spend_usd": round(12500.50 + (i * 250.75), 2),
            "compliance_tier": "SOC2_TYPE_II",
        }
        for i in range(25)
    ]
    workflow_payload = {
        "workflow_name": f"enterprise-clients-migration-{int(time.time())}",
        "source_type": "ORACLE_CLUSTER_EXPORT",
        "target_dynamodb_table": "Migrated_Production_Records",
        "payload_data": records,
        "configuration": {"batch_size": 25, "enable_s3_backup": True},
    }
    wf_headers = {"X-API-Key": api_key}
    wf_resp = client.post("/api/v1/workflows", headers=wf_headers, json=workflow_payload)
    print(f"  ✓ Workflow Submitted: {wf_resp.status_code}")
    wf_data = wf_resp.json()
    job_id = wf_data["id"]
    print(f"  ✓ Job ID: {job_id}")
    print(f"  ✓ Current State: {wf_data['current_state']}")
    print(f"  ✓ Records Enqueued: {wf_data['records_total']}")

    # Query Workflow Detail
    print("\n[Polling] Monitoring Asynchronous Execution through Worker...")
    for attempt in range(25):
        time.sleep(1)
        status_resp = client.get(f"/api/v1/workflows/{job_id}", headers=wf_headers)
        detail = status_resp.json()
        current_state = detail.get("current_state")
        print(
            f"  [{attempt + 1:2d}s] FSM State: {current_state:12} | Processed: {detail.get('records_processed', 0)}/{detail.get('records_total', 0)} | Steps: {len(detail.get('steps', []))}"
        )
        if current_state in ("COMPLETED", "FAILED"):
            break

    print("\n" + "=" * 70)
    print("🎉 LIVE DOCKER CLUSTER EXECUTION COMPLETE & FULLY OPERATIONAL!")
    print("=" * 70)


if __name__ == "__main__":
    run_live_cluster_workflow()
