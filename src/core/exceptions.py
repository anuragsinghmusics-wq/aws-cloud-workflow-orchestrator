"""Domain-specific exception hierarchy for the Cloud Workflow Orchestrator.

Provides structured, typed exceptions with standardized error codes, HTTP status mappings,
retryability classification, and contextual diagnostics.
"""

from typing import Any


class OrchestratorError(Exception):
    """Base exception for all workflow orchestrator domain errors.

    Attributes:
        message: Human-readable error description.
        error_code: Machine-readable uppercase identifier (e.g. ERR_STATE_INVALID_TRANSITION).
        http_status_code: Suggested HTTP response status for REST API mapping.
        retryable: Whether this failure is transient and can be retried by the scheduler.
        details: Additional context dictionary for debugging and structured logs.
    """

    default_message: str = "An unexpected orchestration error occurred."
    default_error_code: str = "ERR_INTERNAL_ORCHESTRATION"
    default_http_status: int = 500
    default_retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        http_status_code: int | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.error_code = error_code or self.default_error_code
        self.http_status_code = (
            http_status_code if http_status_code is not None else self.default_http_status
        )
        self.retryable = retryable if retryable is not None else self.default_retryable
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serializes exception details to a JSON-compatible dictionary."""
        return {
            "error": self.error_code,
            "message": self.message,
            "status_code": self.http_status_code,
            "retryable": self.retryable,
            "details": self.details,
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.error_code!r}, "
            f"message={self.message!r}, "
            f"retryable={self.retryable})"
        )


# ============================================================================
# Configuration & Environment Errors
# ============================================================================


class ConfigurationError(OrchestratorError):
    """Raised when application settings or environment configurations are invalid."""

    default_message = "Application configuration is invalid or missing required variables."
    default_error_code = "ERR_CONFIG_INVALID"
    default_http_status = 500
    default_retryable = False


class MissingEnvironmentVariableError(ConfigurationError):
    """Raised when a strictly required environment variable is not set."""

    default_message = "A required environment variable was not found."
    default_error_code = "ERR_CONFIG_MISSING_ENV_VAR"


class InvalidServiceEndpointError(ConfigurationError):
    """Raised when a configured AWS or database endpoint URL is malformed or unreachable."""

    default_message = "The configured service endpoint URL is invalid."
    default_error_code = "ERR_CONFIG_INVALID_ENDPOINT"


# ============================================================================
# State Machine & Lifecycle Errors
# ============================================================================


class StateMachineError(OrchestratorError):
    """Base error for Finite State Machine execution failures."""

    default_message = "A state machine transition or lifecycle error occurred."
    default_error_code = "ERR_STATE_MACHINE"
    default_http_status = 400
    default_retryable = False


class InvalidStateTransitionError(StateMachineError):
    """Raised when attempting an unauthorized or invalid state transition."""

    default_message = "The requested state transition is not allowed."
    default_error_code = "ERR_STATE_INVALID_TRANSITION"
    default_http_status = 409
    default_retryable = False

    def __init__(
        self,
        from_state: Any = None,
        to_state: Any = None,
        allowed_states: Any | None = None,
        message: str | None = None,
    ) -> None:
        if message is None and from_state is not None and to_state is not None:
            allowed_str = f", allowed: {list(allowed_states)}" if allowed_states else ""
            message = (
                f"Cannot transition workflow from '{from_state}' to '{to_state}'{allowed_str}."
            )
        super().__init__(
            message=message,
            details={
                "from_state": str(from_state) if from_state else None,
                "to_state": str(to_state) if to_state else None,
                "allowed_states": [str(s) for s in allowed_states] if allowed_states else [],
            },
        )


class TerminalStateError(StateMachineError):
    """Raised when trying to mutate or transition a workflow that is already completed or failed."""

    default_message = "Workflow has reached a terminal state and cannot be mutated further."
    default_error_code = "ERR_STATE_TERMINAL"
    default_http_status = 409
    default_retryable = False


class StatePersistenceError(StateMachineError):
    """Raised when saving or loading workflow state from DynamoDB/Postgres fails."""

    default_message = "Failed to persist state machine progress to the ledger."
    default_error_code = "ERR_STATE_PERSISTENCE_FAILED"
    default_http_status = 500
    default_retryable = True


# ============================================================================
# Validation & Data Integrity Errors
# ============================================================================


class ValidationError(OrchestratorError, ValueError):
    """Base error for client payload, schema, or configuration validation failures."""

    default_message = "Payload or parameter validation failed."
    default_error_code = "ERR_VALIDATION"
    default_http_status = 422
    default_retryable = False


class InvalidPayloadError(ValidationError):
    """Raised when migration payload data format, schema, or size violates contract."""

    default_message = "Provided migration payload is malformed or invalid."
    default_error_code = "ERR_PAYLOAD_INVALID"


class ChecksumMismatchError(ValidationError):
    """Raised when payload SHA-256 integrity verification fails against S3/ledger."""

    default_message = "Payload checksum mismatch detected; data corruption suspected."
    default_error_code = "ERR_PAYLOAD_CHECKSUM_MISMATCH"
    default_http_status = 400
    default_retryable = False


class SchemaValidationError(ValidationError):
    """Raised when payload items do not conform to the expected target schema."""

    default_message = "Source data does not conform to the target DynamoDB schema definition."
    default_error_code = "ERR_SCHEMA_VALIDATION_FAILED"


# ============================================================================
# AWS S3 Storage Errors
# ============================================================================


class StorageError(OrchestratorError):
    """Base error for object storage operations."""

    default_message = "An object storage operation failed."
    default_error_code = "ERR_STORAGE"
    default_http_status = 502
    default_retryable = True


class S3BucketNotFoundError(StorageError):
    """Raised when the configured S3 bucket does not exist."""

    default_message = "The specified S3 bucket does not exist."
    default_error_code = "ERR_S3_BUCKET_NOT_FOUND"
    default_http_status = 404
    default_retryable = False


class S3UploadError(StorageError):
    """Raised when uploading migration payloads or artifacts to S3 fails."""

    default_message = "Failed to upload payload artifact to Amazon S3."
    default_error_code = "ERR_S3_UPLOAD_FAILED"
    default_retryable = True


class S3DownloadError(StorageError):
    """Raised when retrieving staged payloads or schemas from S3 fails."""

    default_message = "Failed to download payload artifact from Amazon S3."
    default_error_code = "ERR_S3_DOWNLOAD_FAILED"
    default_retryable = True


class S3PayloadCorruptedError(StorageError):
    """Raised when downloaded S3 content cannot be parsed or has invalid byte length."""

    default_message = "Downloaded S3 payload artifact is corrupt or unreadable."
    default_error_code = "ERR_S3_PAYLOAD_CORRUPT"
    default_retryable = False


# ============================================================================
# Amazon DynamoDB Errors
# ============================================================================


class DatabaseError(OrchestratorError):
    """Base error for database and persistent store operations."""

    default_message = "A persistent database operation failed."
    default_error_code = "ERR_DATABASE"
    default_http_status = 500
    default_retryable = True


class DynamoDBError(DatabaseError):
    """Base error for DynamoDB interactions."""

    default_message = "Amazon DynamoDB operation failed."
    default_error_code = "ERR_DYNAMODB"
    default_http_status = 502
    default_retryable = True


class DynamoDBThrottleError(DynamoDBError):
    """Raised when DynamoDB provisioned throughput is exceeded (HTTP 400 / 503)."""

    default_message = (
        "DynamoDB provisioned throughput exceeded; request throttled by storage layer."
    )
    default_error_code = "ERR_DYNAMODB_THROTTLED"
    default_http_status = 429
    default_retryable = True


class DynamoDBItemNotFoundError(DynamoDBError):
    """Raised when a requested workflow record or ledger item does not exist."""

    default_message = "The requested DynamoDB item was not found."
    default_error_code = "ERR_DYNAMODB_ITEM_NOT_FOUND"
    default_http_status = 404
    default_retryable = False


class ConditionalCheckFailedError(DynamoDBError):
    """Raised when an atomic conditional write fails due to state race or conflict."""

    default_message = (
        "DynamoDB conditional check failed; possible concurrent modification or duplicate."
    )
    default_error_code = "ERR_DYNAMODB_CONDITIONAL_CHECK_FAILED"
    default_http_status = 409
    default_retryable = False


class BatchWritePartialFailureError(DynamoDBError):
    """Raised when a batch write to DynamoDB leaves unprocessed items after retries."""

    default_message = "DynamoDB batch write could not process all items within retry budget."
    default_error_code = "ERR_DYNAMODB_BATCH_WRITE_PARTIAL"
    default_retryable = True


# ============================================================================
# Task Scheduler, Worker Pool & Concurrency Errors
# ============================================================================


class SchedulerError(OrchestratorError):
    """Base error for task dispatch, scheduling, and worker pool operations."""

    default_message = "A task scheduler or worker pool error occurred."
    default_error_code = "ERR_SCHEDULER"
    default_http_status = 500
    default_retryable = True


class TaskExecutionError(SchedulerError):
    """Raised when worker execution of a workflow step fails."""

    default_message = "Execution of workflow phase task failed."
    default_error_code = "ERR_TASK_EXECUTION_FAILED"
    default_retryable = True


class MaxRetriesExceededError(SchedulerError):
    """Raised when an operation has exhausted all configured exponential backoff attempts."""

    default_message = "Operation failed repeatedly and exhausted the maximum retry limit."
    default_error_code = "ERR_MAX_RETRIES_EXCEEDED"
    default_http_status = 504
    default_retryable = False


class CircuitBreakerOpenError(SchedulerError):
    """Raised when an outgoing call to a dependency is blocked by an open circuit breaker."""

    default_message = (
        "Service circuit breaker is OPEN due to elevated failure rates; call rejected fast."
    )
    default_error_code = "ERR_CIRCUIT_BREAKER_OPEN"
    default_http_status = 503
    default_retryable = True


class TaskTimeoutError(SchedulerError):
    """Raised when a workflow task exceeds its maximum execution deadline."""

    default_message = "Task execution exceeded the allowable deadline timeout."
    default_error_code = "ERR_TASK_TIMEOUT"
    default_http_status = 504
    default_retryable = True


class ZombieTaskDetectedError(SchedulerError):
    """Raised when a worker task ceases heartbeats and is reclaimed as a zombie."""

    default_message = "Worker task heartbeat timed out; flagged and reclaimed as a zombie task."
    default_error_code = "ERR_ZOMBIE_TASK_DETECTED"
    default_retryable = True


# ============================================================================
# Amazon CloudWatch & Observability Errors
# ============================================================================


class CloudWatchError(OrchestratorError):
    """Base error for CloudWatch telemetry, logging, and metrics."""

    default_message = "Amazon CloudWatch operation failed."
    default_error_code = "ERR_CLOUDWATCH"
    default_http_status = 502
    default_retryable = True


class MetricPublishError(CloudWatchError):
    """Raised when emitting custom CloudWatch metrics fails."""

    default_message = "Failed to publish workflow performance metrics to Amazon CloudWatch."
    default_error_code = "ERR_CLOUDWATCH_METRIC_PUBLISH_FAILED"
    default_retryable = True


class AlarmDispatchError(CloudWatchError):
    """Raised when configuring or triggering an operational alarm fails."""

    default_message = "Failed to dispatch CloudWatch alert alarm."
    default_error_code = "ERR_CLOUDWATCH_ALARM_DISPATCH_FAILED"
    default_retryable = True


# ============================================================================
# Security & Authentication Errors
# ============================================================================


class AuthenticationError(OrchestratorError):
    """Base error for identity, authentication, and authorization failures."""

    default_message = "Authentication credentials missing, invalid, or expired."
    default_error_code = "ERR_AUTHENTICATION"
    default_http_status = 401
    default_retryable = False


class InvalidCredentialsError(AuthenticationError):
    """Raised when username, password, or API key verification fails."""

    default_message = "Invalid username or password provided."
    default_error_code = "ERR_AUTH_INVALID_CREDENTIALS"


class TokenExpiredError(AuthenticationError):
    """Raised when JWT access or refresh token has expired."""

    default_message = "Session token has expired. Please authenticate again."
    default_error_code = "ERR_AUTH_TOKEN_EXPIRED"


class InsufficientPermissionsError(AuthenticationError):
    """Raised when authenticated subject lacks required RBAC role or permission."""

    default_message = "User does not have sufficient permissions to perform this action."
    default_error_code = "ERR_AUTH_FORBIDDEN"
    default_http_status = 403


class UserAlreadyExistsError(AuthenticationError):
    """Raised when attempting to register an account with an existing email."""

    default_message = "A user account with this email address already exists."
    default_error_code = "ERR_AUTH_USER_ALREADY_EXISTS"
    default_http_status = 409


class ResourceNotFoundError(OrchestratorError):
    """Raised when a requested entity does not exist."""

    default_message = "The requested resource could not be found."
    default_error_code = "ERR_RESOURCE_NOT_FOUND"
    default_http_status = 404


class WorkflowNotFoundError(ResourceNotFoundError):
    """Raised when querying or mutating a non-existent workflow job."""

    default_message = "The requested workflow job ID does not exist."
    default_error_code = "ERR_WORKFLOW_NOT_FOUND"
