"""Integration tests for the end-to-end workflow migration pipeline with Moto mocks."""

import importlib.util
import unittest

HAS_AWS_DEPS = (
    importlib.util.find_spec("boto3") is not None and importlib.util.find_spec("moto") is not None
)
if HAS_AWS_DEPS:
    from moto import mock_aws

    from src.config import Settings
    from src.core.state_machine import WorkflowState
    from src.services.cloudwatch_service import CloudWatchService
    from src.services.dynamodb_service import DynamoDBService
    from src.services.s3_service import S3Service
    from src.workers.pipeline import WorkflowPipelineExecutor


@unittest.skipUnless(HAS_AWS_DEPS, "boto3 and moto required for pipeline integration tests")
class TestWorkflowPipeline(unittest.TestCase):
    """Verifies that the multi-phase pipeline executes deterministically through all FSM states."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()

        self.settings = Settings(
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="testing",
            AWS_SECRET_ACCESS_KEY="testing",
            USE_LOCALSTACK=False,
            S3_BUCKET_NAME="pipeline-test-staging",
            DYNAMODB_STATE_TABLE="Pipeline_Workflow_Ledger",
            CLOUDWATCH_NAMESPACE="PipelineTestNamespace",
        )

        self.s3_service = S3Service(settings=self.settings)
        self.ddb_service = DynamoDBService(settings=self.settings)
        self.cw_service = CloudWatchService(settings=self.settings)

        self.s3_service.ensure_bucket_exists()
        self.ddb_service.ensure_table_exists(
            table_name=self.settings.DYNAMODB_STATE_TABLE,
            partition_key="job_id",
        )

        self.executor = WorkflowPipelineExecutor(
            settings=self.settings,
            s3_service=self.s3_service,
            dynamodb_service=self.ddb_service,
            cloudwatch_service=self.cw_service,
        )

    def tearDown(self):
        self.mock_aws.stop()

    def test_pipeline_happy_path_execution(self):
        records = [
            {"id": f"usr_{i}", "name": f"User {i}", "email": f"u{i}@example.com"} for i in range(15)
        ]
        target_table = "Production_Users"
        job_id = "job-pipe-001"

        result = self.executor.execute_workflow(
            job_id=job_id,
            workflow_name="pg-users-to-dynamodb",
            payload_data=records,
            target_table=target_table,
            source_type="POSTGRES_SQL_DUMP",
            configuration={"batch_size": 10, "partition_key": "id"},
        )

        self.assertEqual(result.final_state, WorkflowState.COMPLETED)
        self.assertEqual(result.records_total, 15)
        self.assertEqual(result.records_processed, 15)
        self.assertEqual(result.records_failed, 0)
        self.assertTrue(result.s3_checksum)
        self.assertIn("s3://pipeline-test-staging/", result.s3_uri)
        self.assertGreater(result.duration_ms, 0)

        # Verify DynamoDB ledger checkpoint
        ledger_state = self.ddb_service.get_workflow_state(job_id=job_id)
        self.assertEqual(ledger_state["current_state"], "COMPLETED")
        self.assertEqual(ledger_state["records_processed"], 15)

        # Verify S3 payload staging
        staged = self.s3_service.retrieve_payload(
            key=f"{self.settings.S3_STAGING_PREFIX}/{job_id}.json",
            expected_checksum=result.s3_checksum,
        )
        self.assertEqual(len(staged), 15)
        self.assertEqual(staged[0]["name"], "User 0")

    def test_pipeline_failure_on_empty_payload(self):
        job_id = "job-fail-empty"
        result = self.executor.execute_workflow(
            job_id=job_id,
            workflow_name="bad-job",
            payload_data=[],
            target_table="Bad_Table",
        )

        self.assertEqual(result.final_state, WorkflowState.FAILED)
        self.assertEqual(result.records_processed, 0)
        self.assertIn("non-empty list", result.error_message)

        # Ledger records FAILED
        ledger_state = self.ddb_service.get_workflow_state(job_id=job_id)
        self.assertEqual(ledger_state["current_state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
