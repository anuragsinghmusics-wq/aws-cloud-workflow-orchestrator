"""End-to-end integration test exercising the complete user journey:

Auth Registration -> Login -> API Key Generation -> Machine-to-Machine Workflow Initiation
-> 6-Phase Pipeline Execution (S3 + DynamoDB + CloudWatch) -> Live Status Querying -> Metrics Telemetry.
"""

import importlib.util
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.database import get_db_session
from src.main import app
from src.models.audit import ApiKey
from src.models.user import User, UserRole
from src.models.workflow import StepStatus, Workflow, WorkflowStep

HAS_AWS_DEPS = (
    importlib.util.find_spec("boto3") is not None and importlib.util.find_spec("moto") is not None
)
if HAS_AWS_DEPS:
    from moto import mock_aws

    from src.config import Settings
    from src.core.idempotency import compute_payload_checksum, generate_deterministic_job_id
    from src.core.security import hash_api_key, hash_password
    from src.core.state_machine import WorkflowState
    from src.services.cloudwatch_service import CloudWatchService
    from src.services.dynamodb_service import DynamoDBService
    from src.services.s3_service import S3Service
    from src.workers.pipeline import WorkflowPipelineExecutor


@unittest.skipUnless(HAS_AWS_DEPS, "boto3 and moto required for E2E integration test")
class TestEndToEndWorkflowLifecycle(unittest.TestCase):
    """Full lifecycle integration test validating end-to-end migration flow."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()

        self.settings = Settings(
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="testing",
            AWS_SECRET_ACCESS_KEY="testing",
            USE_LOCALSTACK=False,
            S3_BUCKET_NAME="e2e-payload-staging",
            DYNAMODB_STATE_TABLE="E2E_Workflow_Ledger",
            CLOUDWATCH_NAMESPACE="E2ETestNamespace",
        )

        self.s3_service = S3Service(settings=self.settings)
        self.ddb_service = DynamoDBService(settings=self.settings)
        self.cw_service = CloudWatchService(settings=self.settings)

        self.s3_service.ensure_bucket_exists()
        self.ddb_service.ensure_table_exists(
            table_name=self.settings.DYNAMODB_STATE_TABLE,
            partition_key="job_id",
        )

        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        app.dependency_overrides[get_db_session] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()
        self.mock_aws.stop()

    @patch("src.api.v1.workflows.execute_migration_task")
    def test_complete_e2e_migration_journey(self, mock_celery_task):
        # --------------------------------------------------------------------
        # Step 1: User Registration
        # --------------------------------------------------------------------
        mock_find_user = MagicMock()
        mock_find_user.scalar_one_or_none.return_value = None  # Not existing
        self.mock_session.execute.return_value = mock_find_user

        reg_payload = {
            "email": "lead.architect@enterprise.com",
            "password": "SecurePassword2026!",
            "full_name": "Lead Cloud Architect",
            "role": "ADMIN",
        }
        reg_response = self.client.post("/api/v1/auth/register", json=reg_payload)
        self.assertEqual(reg_response.status_code, 201)
        user_data = reg_response.json()
        user_id = user_data["id"]
        self.assertEqual(user_data["email"], "lead.architect@enterprise.com")
        self.assertEqual(user_data["role"], "ADMIN")

        # --------------------------------------------------------------------
        # Step 2: User Login & JWT Token Retrieval
        # --------------------------------------------------------------------
        user_entity = User(
            id=user_id,
            email="lead.architect@enterprise.com",
            hashed_password=hash_password("SecurePassword2026!"),
            role=UserRole.ADMIN.value,
            is_active=True,
            is_superuser=True,
        )
        mock_login_res = MagicMock()
        mock_login_res.scalar_one_or_none.return_value = user_entity
        self.mock_session.execute.return_value = mock_login_res

        login_res = self.client.post(
            "/api/v1/auth/login",
            json={"email": "lead.architect@enterprise.com", "password": "SecurePassword2026!"},
        )
        self.assertEqual(login_res.status_code, 200)
        tokens = login_res.json()
        access_token = tokens["access_token"]
        auth_headers = {"Authorization": f"Bearer {access_token}"}

        # --------------------------------------------------------------------
        # Step 3: Caller Profile Verification
        # --------------------------------------------------------------------
        profile_res = self.client.get("/api/v1/auth/me", headers=auth_headers)
        self.assertEqual(profile_res.status_code, 200)
        self.assertEqual(profile_res.json()["id"], user_id)

        # --------------------------------------------------------------------
        # Step 4: Machine-to-Machine API Key Provisioning
        # --------------------------------------------------------------------
        key_res = self.client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Nightly ETL Runner"},
            headers=auth_headers,
        )
        self.assertEqual(key_res.status_code, 201)
        key_data = key_res.json()
        raw_api_key = key_data["raw_key"]
        self.assertTrue(raw_api_key.startswith("cwo_"))

        # Configure mock to recognize the API key
        api_key_entity = ApiKey(
            id=key_data["id"],
            name="Nightly ETL Runner",
            key_hash=hash_api_key(raw_api_key),
            prefix=key_data["prefix"],
            user_id=user_id,
            is_active=True,
        )

        # --------------------------------------------------------------------
        # Step 5: Workflow Job Submission via Machine API Key (X-API-Key)
        # --------------------------------------------------------------------
        target_table = "Production_E2E_Customers"
        self.ddb_service.ensure_table_exists(table_name=target_table, partition_key="customer_id")

        payload_records = [
            {
                "customer_id": "c-001",
                "name": "Global Retail Corp",
                "tier": "ENTERPRISE",
                "balance": 150000,
            },
            {"customer_id": "c-002", "name": "Acme Logistics", "tier": "GROWTH", "balance": 45000},
            {
                "customer_id": "c-003",
                "name": "Nexus Financial",
                "tier": "ENTERPRISE",
                "balance": 820000,
            },
        ]

        expected_job_id = generate_deterministic_job_id(
            workflow_name="e2e-customers-migration",
            source_type="POSTGRES_SQL_DUMP",
            target_table=target_table,
            payload_data=payload_records,
        )
        expected_checksum = compute_payload_checksum(payload_records)

        # Mock query responses for API key validation and workflow insertion
        mock_key_query = MagicMock()
        mock_key_query.scalar_one_or_none.return_value = api_key_entity

        mock_user_query = MagicMock()
        mock_user_query.scalar_one_or_none.return_value = user_entity

        mock_no_duplicate = MagicMock()
        mock_no_duplicate.scalar_one_or_none.return_value = None

        wf_created = Workflow(
            id=expected_job_id,
            workflow_name="e2e-customers-migration",
            source_type="POSTGRES_SQL_DUMP",
            target_dynamodb_table=target_table,
            records_total=3,
            current_state=WorkflowState.PENDING.value,
            s3_checksum=expected_checksum,
            user_id=user_id,
        )
        mock_get_wf = MagicMock()
        mock_get_wf.scalar_one.return_value = wf_created

        self.mock_session.execute.side_effect = [
            mock_key_query,  # select ApiKey
            mock_user_query,  # select User
            mock_no_duplicate,  # select Workflow existing
            mock_get_wf,  # select Workflow created
        ]

        wf_submit_res = self.client.post(
            "/api/v1/workflows",
            headers={"X-API-Key": raw_api_key},
            json={
                "workflow_name": "e2e-customers-migration",
                "source_type": "POSTGRES_SQL_DUMP",
                "target_dynamodb_table": target_table,
                "payload_data": payload_records,
                "configuration": {"batch_size": 25, "max_retries": 3},
            },
        )
        self.assertEqual(wf_submit_res.status_code, 202)
        wf_resp_data = wf_submit_res.json()
        self.assertEqual(wf_resp_data["id"], expected_job_id)
        self.assertEqual(wf_resp_data["current_state"], "PENDING")
        self.assertEqual(wf_resp_data["records_total"], 3)

        # --------------------------------------------------------------------
        # Step 6: Multi-Phase Pipeline Execution (Extract -> Transform -> Load -> Verify)
        # --------------------------------------------------------------------
        executor = WorkflowPipelineExecutor(
            settings=self.settings,
            s3_service=self.s3_service,
            dynamodb_service=self.ddb_service,
            cloudwatch_service=self.cw_service,
        )

        pipeline_result = executor.execute_workflow(
            job_id=expected_job_id,
            workflow_name="e2e-customers-migration",
            payload_data=payload_records,
            target_table=target_table,
            source_type="POSTGRES_SQL_DUMP",
        )

        # Verify pipeline execution outcome
        self.assertEqual(pipeline_result.final_state, WorkflowState.COMPLETED)
        self.assertEqual(pipeline_result.records_processed, 3)
        self.assertEqual(pipeline_result.records_failed, 0)
        self.assertIsNotNone(pipeline_result.s3_uri)
        self.assertIsNotNone(pipeline_result.s3_checksum)
        self.assertEqual(len(pipeline_result.s3_checksum), 64)

        # Verify DynamoDB destination table received all migrated items
        items_in_ddb = self.ddb_service.scan_records(table_name=target_table)
        self.assertEqual(len(items_in_ddb), 3)
        customer_ids = {item["customer_id"] for item in items_in_ddb}
        self.assertEqual(customer_ids, {"c-001", "c-002", "c-003"})

        # --------------------------------------------------------------------
        # Step 7: Workflow Detail & Step Ledger Audit Verification
        # --------------------------------------------------------------------
        wf_completed = Workflow(
            id=expected_job_id,
            workflow_name="e2e-customers-migration",
            source_type="POSTGRES_SQL_DUMP",
            target_dynamodb_table=target_table,
            records_total=3,
            records_processed=3,
            records_failed=0,
            current_state=WorkflowState.COMPLETED.value,
            s3_staging_uri=pipeline_result.s3_uri,
            s3_checksum=pipeline_result.s3_checksum,
            user_id=user_id,
        )
        wf_completed.steps = [
            WorkflowStep(
                workflow_id=expected_job_id,
                from_state="PENDING",
                to_state="EXTRACTING",
                status=StepStatus.SUCCESS.value,
                execution_duration_ms=45.2,
            ),
            WorkflowStep(
                workflow_id=expected_job_id,
                from_state="EXTRACTING",
                to_state="TRANSFORMING",
                status=StepStatus.SUCCESS.value,
                execution_duration_ms=12.1,
            ),
            WorkflowStep(
                workflow_id=expected_job_id,
                from_state="TRANSFORMING",
                to_state="LOADING",
                status=StepStatus.SUCCESS.value,
                execution_duration_ms=98.5,
            ),
            WorkflowStep(
                workflow_id=expected_job_id,
                from_state="LOADING",
                to_state="VERIFYING",
                status=StepStatus.SUCCESS.value,
                execution_duration_ms=30.0,
            ),
            WorkflowStep(
                workflow_id=expected_job_id,
                from_state="VERIFYING",
                to_state="COMPLETED",
                status=StepStatus.SUCCESS.value,
                execution_duration_ms=5.0,
            ),
        ]

        mock_detail_res = MagicMock()
        mock_detail_res.scalar_one_or_none.return_value = wf_completed
        self.mock_session.execute.side_effect = [
            mock_user_query,  # select User from token
            mock_detail_res,  # select Workflow detail
        ]

        detail_response = self.client.get(
            f"/api/v1/workflows/{expected_job_id}",
            headers=auth_headers,
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_data = detail_response.json()
        self.assertEqual(detail_data["id"], expected_job_id)
        self.assertEqual(detail_data["current_state"], "COMPLETED")
        self.assertEqual(detail_data["progress_percentage"], 100.0)
        self.assertEqual(len(detail_data["steps"]), 5)
        self.assertEqual(detail_data["steps"][-1]["to_state"], "COMPLETED")

        # --------------------------------------------------------------------
        # Step 8: Telemetry Metrics Export
        # --------------------------------------------------------------------
        mock_metrics_state = MagicMock()
        mock_metrics_state.all.return_value = [("COMPLETED", 1)]
        mock_metrics_vol = MagicMock()
        mock_metrics_vol.one.return_value = (3, 3, 0)

        self.mock_session.execute.side_effect = [
            mock_user_query,
            mock_metrics_state,
            mock_metrics_vol,
        ]

        metrics_res = self.client.get("/api/v1/metrics", headers=auth_headers)
        self.assertEqual(metrics_res.status_code, 200)
        metrics_data = metrics_res.json()
        self.assertEqual(metrics_data["workflows"]["total"], 1)
        self.assertEqual(metrics_data["workflows"]["success_rate_percent"], 100.0)
        self.assertEqual(metrics_data["records"]["total_processed"], 3)


if __name__ == "__main__":
    unittest.main()
