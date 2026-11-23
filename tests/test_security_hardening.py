"""Unit and integration tests for Security Hardening, Input Sanitization, and OWASP Headers."""

import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from src.api.schemas.workflow_schemas import WorkflowCreateRequest
from src.core.exceptions import ValidationError
from src.core.security_validation import (
    sanitize_html,
    validate_dynamodb_table_name,
    validate_payload_depth,
    validate_payload_records,
    validate_s3_key,
)
from src.database import get_db_session
from src.main import app


class TestSecurityValidationEngine(unittest.TestCase):
    """Verifies input sanitization against path traversal, XSS, injection, and payload bombs."""

    def test_s3_key_valid_patterns(self):
        valid_keys = [
            "staging/job-123.json",
            "migrations/tenant-a/2026/payload.json",
            "ledger_snapshot.json",
        ]
        for key in valid_keys:
            self.assertEqual(validate_s3_key(key), key)

    def test_s3_key_path_traversal_rejections(self):
        malicious_keys = [
            "../etc/passwd",
            "staging/../../secrets.env",
            "staging/../config.py",
            "staging/./current.json",
            "/absolute/leading/slash.json",
            "windows\\backslash\\escape.json",
            "poison\0nullbyte.json",
        ]
        for key in malicious_keys:
            with self.assertRaises(ValidationError, msg=f"Should reject: {key}"):
                validate_s3_key(key)

    def test_dynamodb_table_name_validation(self):
        valid_tables = [
            "Users_V2",
            "production-events-2026",
            "Tenant.Data_Store",
            "abc",
        ]
        for table in valid_tables:
            self.assertEqual(validate_dynamodb_table_name(table), table)

        invalid_tables = [
            "ab",  # too short (<3)
            "Users; DROP TABLE users;--",  # SQL injection syntax
            "table name with spaces",
            "table$name",
            "<script>alert(1)</script>",
            "a" * 256,  # too long (>255)
        ]
        for table in invalid_tables:
            with self.assertRaises(ValidationError, msg=f"Should reject: {table}"):
                validate_dynamodb_table_name(table)

    def test_xss_html_sanitization(self):
        malicious_html = "<script>alert('XSS')</script>"
        sanitized = sanitize_html(malicious_html)
        self.assertNotIn("<script>", sanitized)
        self.assertIn("&lt;script&gt;", sanitized)
        self.assertIn("&lt;/script&gt;", sanitized)

        img_xss = '<img src=x onerror="alert(1)">'
        sanitized_img = sanitize_html(img_xss)
        self.assertNotIn("<img", sanitized_img)
        self.assertIn("&quot;", sanitized_img)

    def test_payload_bomb_nesting_depth_detection(self):
        # Safe nested payload (depth = 3)
        safe_data = {"a": {"b": {"c": 123}}}
        validate_payload_depth(safe_data, max_depth=5)  # Should pass without error

        # Malicious deeply nested payload (depth = 7 > max 5)
        bomb_data: dict = {}
        curr = bomb_data
        for i in range(8):
            curr[f"nested_{i}"] = {}
            curr = curr[f"nested_{i}"]

        with self.assertRaises(ValidationError):
            validate_payload_depth(bomb_data, max_depth=5)

    def test_payload_records_validation(self):
        valid_records = [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]
        self.assertEqual(validate_payload_records(valid_records), valid_records)

        with self.assertRaises(ValidationError):
            validate_payload_records([])

        with self.assertRaises(ValidationError):
            validate_payload_records(["not-a-dict"])  # type: ignore


class TestPydanticSchemaSecurityEnforcement(unittest.TestCase):
    """Verifies that Pydantic workflow schemas automatically enforce security constraints."""

    def test_workflow_name_xss_auto_sanitization(self):
        payload = {
            "workflow_name": "<b>Important Migration</b> <script>steal()</script>",
            "source_type": "JSON",
            "target_dynamodb_table": "SafeTable_V1",
            "payload_data": [{"col": "val"}],
        }
        wf_req = WorkflowCreateRequest(**payload)
        self.assertNotIn("<script>", wf_req.workflow_name)
        self.assertIn("&lt;script&gt;", wf_req.workflow_name)

    def test_target_table_injection_rejection(self):
        payload = {
            "workflow_name": "Standard Migration",
            "source_type": "JSON",
            "target_dynamodb_table": "Users; DELETE * FROM users",
            "payload_data": [{"col": "val"}],
        }
        with self.assertRaises(PydanticValidationError):
            WorkflowCreateRequest(**payload)

    def test_payload_bomb_rejected_by_schema(self):
        deep_bomb: dict = {}
        curr = deep_bomb
        for _i in range(10):
            curr["lvl"] = {}
            curr = curr["lvl"]

        payload = {
            "workflow_name": "Standard Migration",
            "source_type": "JSON",
            "target_dynamodb_table": "Users_V1",
            "payload_data": [{"col": deep_bomb}],
        }
        with self.assertRaises(PydanticValidationError):
            WorkflowCreateRequest(**payload)


class TestOWASPSecurityHeaders(unittest.TestCase):
    """Verifies that all API responses include standard OWASP defensive headers."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()

        async def override_db():
            yield self.mock_session

        app.dependency_overrides[get_db_session] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_security_headers_present_on_api_responses(self):
        res = self.client.get("/api/v1/health/live")
        self.assertEqual(res.status_code, 200)

        # Verify OWASP headers
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("max-age=31536000", res.headers.get("Strict-Transport-Security", ""))
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy", ""))
        self.assertIn("geolocation=()", res.headers.get("Permissions-Policy", ""))
        self.assertEqual(res.headers.get("X-Permitted-Cross-Domain-Policies"), "none")


if __name__ == "__main__":
    unittest.main()
