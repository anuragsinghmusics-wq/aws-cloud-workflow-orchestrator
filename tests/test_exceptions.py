"""Unit tests for the domain-specific exception hierarchy."""

import unittest

from src.core.exceptions import (
    CircuitBreakerOpenError,
    ConfigurationError,
    DynamoDBThrottleError,
    InvalidPayloadError,
    InvalidStateTransitionError,
    MaxRetriesExceededError,
    OrchestratorError,
    S3PayloadCorruptedError,
    S3UploadError,
    StateMachineError,
    TerminalStateError,
    ValidationError,
)


class TestOrchestratorExceptions(unittest.TestCase):
    """Verifies that all domain exceptions carry proper codes, status codes, and attributes."""

    def test_base_orchestrator_error_defaults(self):
        err = OrchestratorError()
        self.assertEqual(err.error_code, "ERR_INTERNAL_ORCHESTRATION")
        self.assertEqual(err.http_status_code, 500)
        self.assertFalse(err.retryable)
        self.assertEqual(err.details, {})

        data = err.to_dict()
        self.assertEqual(data["error"], "ERR_INTERNAL_ORCHESTRATION")
        self.assertEqual(data["status_code"], 500)
        self.assertFalse(data["retryable"])

    def test_custom_parameters_override(self):
        err = OrchestratorError(
            message="Custom failure",
            error_code="ERR_CUSTOM",
            http_status_code=400,
            retryable=True,
            details={"key": "value"},
        )
        self.assertEqual(err.message, "Custom failure")
        self.assertEqual(err.error_code, "ERR_CUSTOM")
        self.assertEqual(err.http_status_code, 400)
        self.assertTrue(err.retryable)
        self.assertEqual(err.details["key"], "value")

        serialized = err.to_dict()
        self.assertEqual(serialized["details"]["key"], "value")

    def test_invalid_state_transition_error(self):
        err = InvalidStateTransitionError(
            from_state="PENDING",
            to_state="COMPLETED",
            allowed_states=["EXTRACTING", "FAILED"],
        )
        self.assertEqual(err.error_code, "ERR_STATE_INVALID_TRANSITION")
        self.assertEqual(err.http_status_code, 409)
        self.assertFalse(err.retryable)
        self.assertIn("Cannot transition workflow from 'PENDING' to 'COMPLETED'", err.message)
        self.assertEqual(err.details["from_state"], "PENDING")
        self.assertEqual(err.details["to_state"], "COMPLETED")
        self.assertIn("EXTRACTING", err.details["allowed_states"])

    def test_dynamodb_throttle_error_is_retryable(self):
        err = DynamoDBThrottleError()
        self.assertEqual(err.error_code, "ERR_DYNAMODB_THROTTLED")
        self.assertEqual(err.http_status_code, 429)
        self.assertTrue(err.retryable)

    def test_s3_upload_error_is_retryable(self):
        err = S3UploadError()
        self.assertEqual(err.error_code, "ERR_S3_UPLOAD_FAILED")
        self.assertTrue(err.retryable)

    def test_s3_corrupted_payload_not_retryable(self):
        err = S3PayloadCorruptedError()
        self.assertEqual(err.error_code, "ERR_S3_PAYLOAD_CORRUPT")
        self.assertFalse(err.retryable)

    def test_circuit_breaker_open_error(self):
        err = CircuitBreakerOpenError()
        self.assertEqual(err.error_code, "ERR_CIRCUIT_BREAKER_OPEN")
        self.assertEqual(err.http_status_code, 503)
        self.assertTrue(err.retryable)

    def test_max_retries_exceeded_error(self):
        err = MaxRetriesExceededError()
        self.assertEqual(err.error_code, "ERR_MAX_RETRIES_EXCEEDED")
        self.assertEqual(err.http_status_code, 504)
        self.assertFalse(err.retryable)

    def test_exception_inheritance_tree(self):
        self.assertTrue(issubclass(StateMachineError, OrchestratorError))
        self.assertTrue(issubclass(InvalidStateTransitionError, StateMachineError))
        self.assertTrue(issubclass(TerminalStateError, StateMachineError))
        self.assertTrue(issubclass(ValidationError, OrchestratorError))
        self.assertTrue(issubclass(InvalidPayloadError, ValidationError))
        self.assertTrue(issubclass(ConfigurationError, OrchestratorError))


if __name__ == "__main__":
    unittest.main()
