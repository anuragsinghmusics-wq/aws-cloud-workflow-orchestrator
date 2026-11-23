"""Unit and integration tests for AWS S3, DynamoDB, and CloudWatch services using Moto."""

import importlib.util
import unittest

HAS_AWS_DEPS = (
    importlib.util.find_spec("boto3") is not None and importlib.util.find_spec("moto") is not None
)
if HAS_AWS_DEPS:
    from moto import mock_aws

    from src.config import Settings
    from src.core.exceptions import ChecksumMismatchError, ConditionalCheckFailedError
    from src.services.cloudwatch_service import CloudWatchService
    from src.services.dynamodb_service import DynamoDBService
    from src.services.s3_service import S3Service


@unittest.skipUnless(HAS_AWS_DEPS, "boto3 and moto required for AWS service mock tests")
class TestAWSServices(unittest.TestCase):
    """Verifies that S3 payload staging, DynamoDB ledger, and CloudWatch telemetry work reliably."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()

        self.settings = Settings(
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="testing",
            AWS_SECRET_ACCESS_KEY="testing",
            USE_LOCALSTACK=False,
            S3_BUCKET_NAME="test-orchestrator-staging",
            DYNAMODB_STATE_TABLE="Test_Workflow_Ledger",
            CLOUDWATCH_NAMESPACE="TestOrchestrator",
        )

        self.s3_service = S3Service(settings=self.settings)
        self.ddb_service = DynamoDBService(settings=self.settings)
        self.cw_service = CloudWatchService(settings=self.settings)

        # Ensure infrastructure tables and buckets exist in moto mock
        self.s3_service.ensure_bucket_exists()
        self.ddb_service.ensure_table_exists(
            table_name=self.settings.DYNAMODB_STATE_TABLE,
            partition_key="job_id",
        )

    def tearDown(self):
        self.mock_aws.stop()

    def test_s3_stage_and_retrieve_payload(self):
        payload = [
            {"user_id": "usr_001", "name": "Alice Smith", "tier": "Enterprise"},
            {"user_id": "usr_002", "name": "Bob Jones", "tier": "Standard"},
        ]
        result = self.s3_service.stage_payload(job_id="job-101", payload_data=payload)

        self.assertTrue(result.checksum)
        self.assertEqual(result.records_count, 2)
        self.assertIn(f"s3://{self.settings.S3_BUCKET_NAME}/", result.s3_uri)
        self.assertIn("job-101.json", result.s3_uri)

        # Retrieve and verify payload integrity
        retrieved = self.s3_service.retrieve_payload(
            key=result.key,
            expected_checksum=result.checksum,
        )
        self.assertEqual(len(retrieved), 2)
        self.assertEqual(retrieved[0]["name"], "Alice Smith")

    def test_s3_checksum_mismatch_raises(self):
        payload = [{"data": "valid"}]
        result = self.s3_service.stage_payload(job_id="job-bad", payload_data=payload)

        with self.assertRaises(ChecksumMismatchError):
            self.s3_service.retrieve_payload(
                key=result.key,
                expected_checksum="deadbeef1234567890abcdefdeadbeef1234567890abcdefdeadbeef12345678",
            )

    def test_s3_presigned_url_generation(self):
        payload = [{"item": "test"}]
        result = self.s3_service.stage_payload(job_id="job-url", payload_data=payload)
        url = self.s3_service.generate_presigned_url(key=result.key)
        self.assertIn("https://", url)
        self.assertIn("test-orchestrator-staging", url)

    def test_dynamodb_record_and_get_workflow_state(self):
        item = self.ddb_service.record_workflow_state(
            job_id="wf-999",
            state="PENDING",
            metadata={"records_total": 500, "source": "POSTGRES"},
        )
        self.assertEqual(item["current_state"], "PENDING")
        self.assertEqual(item["version"], 1)

        fetched = self.ddb_service.get_workflow_state(job_id="wf-999")
        self.assertEqual(fetched["job_id"], "wf-999")
        self.assertEqual(fetched["current_state"], "PENDING")
        self.assertEqual(fetched["records_total"], 500)

    def test_dynamodb_atomic_optimistic_locking(self):
        self.ddb_service.record_workflow_state(job_id="wf-lock", state="PENDING")

        # Correct version update from 1 to 2
        updated = self.ddb_service.record_workflow_state(
            job_id="wf-lock",
            state="EXTRACTING",
            expected_version=1,
        )
        self.assertEqual(updated["version"], 2)

        # Mismatched version update raises ConditionalCheckFailedError
        with self.assertRaises(ConditionalCheckFailedError):
            self.ddb_service.record_workflow_state(
                job_id="wf-lock",
                state="TRANSFORMING",
                expected_version=1,  # Version is now 2, expecting 1 must fail
            )

    def test_dynamodb_batch_write_records(self):
        target_table = "Target_Users"
        self.ddb_service.ensure_table_exists(table_name=target_table, partition_key="user_id")

        records = [{"user_id": f"usr_{i}", "score": i * 1.5} for i in range(50)]
        result = self.ddb_service.batch_write_records(
            table_name=target_table,
            items=records,
            batch_size=25,
        )
        self.assertEqual(result["processed"], 50)
        self.assertEqual(result["batches"], 2)

    def test_cloudwatch_publish_metric_and_alarm(self):
        # Publish metric
        self.cw_service.publish_metric(
            metric_name="WorkflowDuration",
            value=1240.5,
            unit="Milliseconds",
        )

        # Create alarm
        self.cw_service.create_failure_alarm(alarm_name="HighMigrationFailureRate", threshold=5.0)

        # Health check
        self.assertTrue(self.cw_service.health_check())


if __name__ == "__main__":
    unittest.main()
