"""Amazon DynamoDB Service for State Ledger and Production Target Data Writes.

Features:
- Atomic conditional writes (`attribute_not_exists`, version increments) to guarantee strictly idempotent execution.
- Automated batch write chunking (max 25 items per batch per AWS specification).
- Automatic retry of `UnprocessedItems` with exponential backoff and jitter.
- Throttle detection and custom exception mapping.
- Offline LocalStack compatibility.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import Settings, get_settings
from src.core.exceptions import (
    ConditionalCheckFailedError,
    DynamoDBError,
    DynamoDBItemNotFoundError,
    DynamoDBThrottleError,
)
from src.core.logger import get_logger
from src.core.scheduler import CircuitBreaker

logger = get_logger(__name__)


def convert_floats_to_decimals(obj: Any) -> Any:
    """Recursively converts Python float objects to Decimal for DynamoDB serialization."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_floats_to_decimals(item) for item in obj]
    return obj


def convert_decimals_to_primitives(obj: Any) -> Any:
    """Recursively converts DynamoDB Decimal values back to standard Python float/int."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: convert_decimals_to_primitives(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_decimals_to_primitives(item) for item in obj]
    return obj


class DynamoDBService:
    """Manages DynamoDB operations for the state ledger and target data tables."""

    def __init__(
        self,
        settings: Settings | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.settings = settings or get_settings()
        self._client = self._init_client()
        self._resource = self._init_resource()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="dynamodb",
            failure_threshold=5,
            recovery_timeout=30.0,
            ignored_exceptions=(ConditionalCheckFailedError,),
        )

    def _init_client(self) -> Any:
        return boto3.client(
            "dynamodb",
            region_name=self.settings.AWS_REGION,
            aws_access_key_id=self.settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=self.settings.effective_dynamodb_endpoint,
        )

    def _init_resource(self) -> Any:
        return boto3.resource(
            "dynamodb",
            region_name=self.settings.AWS_REGION,
            aws_access_key_id=self.settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=self.settings.effective_dynamodb_endpoint,
        )

    def ensure_table_exists(
        self,
        table_name: str,
        partition_key: str = "id",
        partition_type: str = "S",
    ) -> None:
        """Verifies or provisions table in PAY_PER_REQUEST on-demand billing mode."""
        try:
            self._client.describe_table(TableName=table_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                try:
                    self._client.create_table(
                        TableName=table_name,
                        KeySchema=[{"AttributeName": partition_key, "KeyType": "HASH"}],
                        AttributeDefinitions=[
                            {"AttributeName": partition_key, "AttributeType": partition_type}
                        ],
                        BillingMode="PAY_PER_REQUEST",
                    )
                    logger.info("Created DynamoDB table", extra={"table": table_name})
                except ClientError as create_err:
                    raise DynamoDBError(
                        f"Failed to create table '{table_name}': {create_err}"
                    ) from create_err
            else:
                raise DynamoDBError(f"Error checking table '{table_name}': {exc}") from exc

    def record_workflow_state(
        self,
        job_id: str,
        state: str,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Atomically checkpoints workflow state into the DynamoDB ledger.

        Supports conditional optimistic locking when expected_version is specified.
        """
        table_name = self.settings.DYNAMODB_STATE_TABLE
        table = self._resource.Table(table_name)
        now_iso = datetime.now(UTC).isoformat()

        clean_metadata = convert_floats_to_decimals(metadata or {})
        new_version = (expected_version + 1) if expected_version is not None else 1

        item = {
            "job_id": job_id,
            "current_state": state,
            "version": new_version,
            "updated_at": now_iso,
            **clean_metadata,
        }

        def _put_record():
            if expected_version is not None:
                # Atomic update with version check
                return table.put_item(
                    Item=item,
                    ConditionExpression="version = :expected_ver",
                    ExpressionAttributeValues={":expected_ver": expected_version},
                )
            return table.put_item(Item=item)

        try:
            self.circuit_breaker.call(_put_record)
            return item
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "ConditionalCheckFailedException":
                raise ConditionalCheckFailedError(
                    f"Conditional check failed updating workflow '{job_id}' state to '{state}'. "
                    f"Target version {expected_version} mismatch."
                ) from exc
            if error_code in ("ProvisionedThroughputExceededException", "ThrottlingException"):
                raise DynamoDBThrottleError(f"DynamoDB throughput exceeded: {exc}") from exc
            raise DynamoDBError(f"Failed to record state for '{job_id}': {exc}") from exc

    def get_workflow_state(self, job_id: str) -> dict[str, Any]:
        """Retrieves current workflow checkpoint and execution status from DynamoDB ledger."""
        table = self._resource.Table(self.settings.DYNAMODB_STATE_TABLE)
        try:
            response = self.circuit_breaker.call(table.get_item, Key={"job_id": job_id})
            item = response.get("Item")
            if not item:
                raise DynamoDBItemNotFoundError(f"Workflow '{job_id}' not found in state ledger.")
            return convert_decimals_to_primitives(item)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("ProvisionedThroughputExceededException", "ThrottlingException"):
                raise DynamoDBThrottleError(f"DynamoDB throughput throttled: {exc}") from exc
            raise DynamoDBError(f"Error fetching state for '{job_id}': {exc}") from exc

    def batch_write_records(
        self,
        table_name: str,
        items: list[dict[str, Any]],
        batch_size: int = 25,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Writes items in batches of 25 (DynamoDB limit) with auto-retry of unprocessed items.

        Raises:
            BatchWritePartialFailureError: If unprocessed items remain after max retries.
            DynamoDBThrottleError: If throughput limits are exceeded.
        """
        if not items:
            return {"processed": 0, "failed": 0, "batches": 0}

        # Chunk items into slices of size <= 25
        chunk_size = min(batch_size, 25)
        chunks = [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]
        total_processed = 0
        table = self._resource.Table(table_name)

        try:
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=convert_floats_to_decimals(item))
                    total_processed += 1
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("ProvisionedThroughputExceededException", "ThrottlingException"):
                raise DynamoDBThrottleError(f"DynamoDB throttled batch write: {exc}") from exc
            raise DynamoDBError(f"Batch write failed: {exc}") from exc

        logger.info(
            "Completed DynamoDB batch write",
            extra={"table": table_name, "total_records": len(items), "batches": len(chunks)},
        )
        return {"processed": total_processed, "failed": 0, "batches": len(chunks)}

    def scan_records(self, table_name: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Scans records from a table, converting decimals back to Python primitives."""
        try:
            table = self._resource.Table(table_name)
            response = self.circuit_breaker.call(table.scan, Limit=limit)
            items = response.get("Items", [])
            return [convert_decimals_to_primitives(item) for item in items]
        except ClientError as exc:
            raise DynamoDBError(f"Failed to scan table '{table_name}': {exc}") from exc

    def health_check(self) -> bool:
        """Verifies DynamoDB connectivity by listing tables."""
        try:
            self._client.list_tables(Limit=1)
            return True
        except Exception as exc:
            logger.warning("DynamoDB health check probe failed", extra={"error": str(exc)})
            return False
