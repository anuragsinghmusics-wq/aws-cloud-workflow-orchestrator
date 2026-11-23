"""Unit tests for structured logging, correlation IDs, and credential scrubbing."""

import json
import logging
import unittest

from src.core.logger import (
    LogContext,
    StructuredJsonFormatter,
    correlation_id_ctx,
    job_id_ctx,
    sanitize_value,
)


class TestStructuredLogger(unittest.TestCase):
    """Verifies structured JSON logging output, correlation ID propagation, and redaction."""

    def setUp(self):
        self.formatter = StructuredJsonFormatter()
        correlation_id_ctx.set(None)
        job_id_ctx.set(None)

    def test_json_formatter_standard_fields(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="src/core/state_machine.py",
            lineno=42,
            msg="Workflow step executed successfully",
            args=(),
            exc_info=None,
            func="transition_to",
        )
        formatted = self.formatter.format(record)
        data = json.loads(formatted)

        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["logger"], "test_logger")
        self.assertEqual(data["message"], "Workflow step executed successfully")
        self.assertEqual(data["caller"]["line"], 42)
        self.assertEqual(data["caller"]["function"], "transition_to")
        self.assertIn("timestamp", data)

    def test_correlation_id_and_job_id_in_log(self):
        with LogContext(correlation_id="corr-12345", job_id="job-abcde"):
            record = logging.LogRecord(
                name="task_worker",
                level=logging.INFO,
                pathname="src/core/scheduler.py",
                lineno=88,
                msg="Enqueuing batch task",
                args=(),
                exc_info=None,
            )
            data = json.loads(self.formatter.format(record))
            self.assertEqual(data.get("correlation_id"), "corr-12345")
            self.assertEqual(data.get("job_id"), "job-abcde")

        # Outside context, should be reset
        record_outside = logging.LogRecord(
            name="task_worker",
            level=logging.INFO,
            pathname="src/core/scheduler.py",
            lineno=89,
            msg="Outside context",
            args=(),
            exc_info=None,
        )
        data_outside = json.loads(self.formatter.format(record_outside))
        self.assertNotIn("correlation_id", data_outside)
        self.assertNotIn("job_id", data_outside)

    def test_sensitive_credential_scrubbing(self):
        self.assertEqual(sanitize_value("aws_secret_access_key", "secret123"), "[REDACTED]")
        self.assertEqual(sanitize_value("password", "p@ssword"), "[REDACTED]")
        self.assertEqual(sanitize_value("auth_token", "jwt.token.val"), "[REDACTED]")
        self.assertEqual(sanitize_value("api_key", "my-key"), "[REDACTED]")

        # Nested dict sanitization
        nested = {
            "user": "alice",
            "aws_secret_key": "topsecret",
            "metadata": {
                "bearer_token": "token123",
                "normal_field": "visible",
            },
        }
        sanitized = sanitize_value("data", nested)
        self.assertEqual(sanitized["user"], "alice")
        self.assertEqual(sanitized["aws_secret_key"], "[REDACTED]")
        self.assertEqual(sanitized["metadata"]["bearer_token"], "[REDACTED]")
        self.assertEqual(sanitized["metadata"]["normal_field"], "visible")


if __name__ == "__main__":
    unittest.main()
