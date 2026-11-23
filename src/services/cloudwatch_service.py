"""Amazon CloudWatch Service for Metrics Telemetry, Alarms, and Log Streaming.

Features:
- Custom metric emission for phase duration, migration throughput, and error rates.
- Operational threshold alarm creation for automated failure alerting.
- Structured CloudWatch Logs event streaming with automated stream creation.
- LocalStack telemetry compatibility.
"""

from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import Settings, get_settings
from src.core.exceptions import AlarmDispatchError, MetricPublishError
from src.core.logger import get_logger
from src.core.scheduler import CircuitBreaker

logger = get_logger(__name__)


class CloudWatchService:
    """Publishes metrics, alarms, and audit log events to Amazon CloudWatch."""

    def __init__(
        self,
        settings: Settings | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.settings = settings or get_settings()
        self._cw_client = self._init_cw_client()
        self._logs_client = self._init_logs_client()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="cloudwatch", failure_threshold=5, recovery_timeout=30.0
        )

    def _init_cw_client(self) -> Any:
        return boto3.client(
            "cloudwatch",
            region_name=self.settings.AWS_REGION,
            aws_access_key_id=self.settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=self.settings.effective_cloudwatch_endpoint,
        )

    def _init_logs_client(self) -> Any:
        return boto3.client(
            "logs",
            region_name=self.settings.AWS_REGION,
            aws_access_key_id=self.settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=self.settings.effective_cloudwatch_endpoint,
        )

    def publish_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "Count",
        dimensions: list[dict[str, str]] | None = None,
    ) -> None:
        """Publishes a custom CloudWatch metric data point under the configured namespace."""
        try:
            self.circuit_breaker.call(
                self._cw_client.put_metric_data,
                Namespace=self.settings.CLOUDWATCH_NAMESPACE,
                MetricData=[
                    {
                        "MetricName": metric_name,
                        "Value": value,
                        "Unit": unit,
                        "Timestamp": datetime.now(UTC),
                        "Dimensions": dimensions or [],
                    }
                ],
            )
        except ClientError as exc:
            logger.warning(
                "Failed to publish CloudWatch metric",
                extra={"metric": metric_name, "value": value, "error": str(exc)},
            )
            raise MetricPublishError(f"Failed to publish metric '{metric_name}': {exc}") from exc

    def record_task_metrics(
        self,
        job_id: str,
        phase: str,
        duration_ms: float,
        records_count: int,
        success: bool = True,
    ) -> None:
        """Emits standard phase performance and outcome metrics."""
        dims = [
            {"Name": "Phase", "Value": phase},
            {"Name": "WorkflowId", "Value": job_id},
        ]

        metric_data = [
            {
                "MetricName": "PhaseDuration",
                "Value": duration_ms,
                "Unit": "Milliseconds",
                "Timestamp": datetime.now(UTC),
                "Dimensions": dims,
            },
            {
                "MetricName": "RecordsProcessed",
                "Value": float(records_count),
                "Unit": "Count",
                "Timestamp": datetime.now(UTC),
                "Dimensions": dims,
            },
            {
                "MetricName": "SuccessCount" if success else "FailureCount",
                "Value": 1.0,
                "Unit": "Count",
                "Timestamp": datetime.now(UTC),
                "Dimensions": dims,
            },
        ]

        try:
            self._cw_client.put_metric_data(
                Namespace=self.settings.CLOUDWATCH_NAMESPACE,
                MetricData=metric_data,
            )
        except ClientError as exc:
            logger.warning("Error publishing composite task metrics", extra={"error": str(exc)})

    def create_failure_alarm(
        self,
        alarm_name: str,
        threshold: float = 1.0,
        period_seconds: int = 60,
        evaluation_periods: int = 1,
    ) -> None:
        """Creates an operational metric alarm triggered when failures exceed threshold."""
        try:
            self._cw_client.put_metric_alarm(
                AlarmName=alarm_name,
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                EvaluationPeriods=evaluation_periods,
                MetricName="FailureCount",
                Namespace=self.settings.CLOUDWATCH_NAMESPACE,
                Period=period_seconds,
                Statistic="Sum",
                Threshold=threshold,
                ActionsEnabled=False,
                AlarmDescription="Triggers when workflow execution failures exceed allowable limits",
            )
            logger.info("Created CloudWatch failure alarm", extra={"alarm_name": alarm_name})
        except ClientError as exc:
            raise AlarmDispatchError(f"Failed to create alarm '{alarm_name}': {exc}") from exc

    def log_workflow_event(
        self,
        stream_name: str,
        message: str,
        log_group: str | None = None,
    ) -> None:
        """Appends a log event to CloudWatch Logs with automated stream provisioning."""
        group = log_group or self.settings.CLOUDWATCH_LOG_GROUP
        try:
            # Ensure log stream exists
            try:
                self._logs_client.create_log_stream(logGroupName=group, logStreamName=stream_name)
            except ClientError as stream_exc:
                if (
                    stream_exc.response.get("Error", {}).get("Code")
                    != "ResourceAlreadyExistsException"
                ):
                    pass

            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            self._logs_client.put_log_events(
                logGroupName=group,
                logStreamName=stream_name,
                logEvents=[{"timestamp": now_ms, "message": message}],
            )
        except ClientError as exc:
            logger.warning("CloudWatch Logs event submission failed", extra={"error": str(exc)})

    def health_check(self) -> bool:
        """Verifies CloudWatch service connectivity."""
        try:
            self._cw_client.list_metrics(Namespace=self.settings.CLOUDWATCH_NAMESPACE)
            return True
        except Exception:
            try:
                self._logs_client.describe_log_groups(limit=1)
                return True
            except Exception as exc:
                logger.warning("CloudWatch health check probe failed", extra={"error": str(exc)})
                return False
