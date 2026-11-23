"""Unit tests for the application settings and configuration module."""

import os
import unittest
from unittest.mock import patch

from src.config import Settings, get_settings


class TestConfiguration(unittest.TestCase):
    """Verifies that configuration values, defaults, and LocalStack fallbacks behave correctly."""

    def test_default_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
            self.assertEqual(settings.PROJECT_NAME, "AWS Cloud-Native Workflow Orchestrator")
            self.assertEqual(settings.VERSION, "0.1.0")
            self.assertEqual(settings.API_V1_PREFIX, "/api/v1")
            self.assertEqual(settings.PORT, 8000)
            self.assertEqual(settings.AWS_REGION, "us-east-1")
            self.assertTrue(settings.USE_LOCALSTACK)
            self.assertEqual(settings.LOCALSTACK_ENDPOINT_URL, "http://localhost:4566")

    def test_effective_endpoints_with_localstack(self):
        settings = Settings(USE_LOCALSTACK=True, LOCALSTACK_ENDPOINT_URL="http://localhost:4566")
        self.assertEqual(settings.effective_s3_endpoint, "http://localhost:4566")
        self.assertEqual(settings.effective_dynamodb_endpoint, "http://localhost:4566")
        self.assertEqual(settings.effective_cloudwatch_endpoint, "http://localhost:4566")

    def test_effective_endpoints_with_custom_overrides(self):
        settings = Settings(
            USE_LOCALSTACK=True,
            S3_ENDPOINT_URL="http://custom-s3:9000",
            DYNAMODB_ENDPOINT_URL="http://custom-dynamodb:8000",
            CLOUDWATCH_ENDPOINT_URL="http://custom-cw:4566",
        )
        self.assertEqual(settings.effective_s3_endpoint, "http://custom-s3:9000")
        self.assertEqual(settings.effective_dynamodb_endpoint, "http://custom-dynamodb:8000")
        self.assertEqual(settings.effective_cloudwatch_endpoint, "http://custom-cw:4566")

    def test_effective_endpoints_production_mode(self):
        settings = Settings(
            USE_LOCALSTACK=False,
            ENVIRONMENT="production",
            S3_ENDPOINT_URL=None,
            DYNAMODB_ENDPOINT_URL=None,
            CLOUDWATCH_ENDPOINT_URL=None,
        )
        self.assertIsNone(settings.effective_s3_endpoint)
        self.assertIsNone(settings.effective_dynamodb_endpoint)
        self.assertIsNone(settings.effective_cloudwatch_endpoint)
        self.assertTrue(settings.is_production)

    def test_environment_variable_override(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "staging", "PORT": "9090", "DEBUG": "true"}):
            settings = Settings()
            self.assertEqual(settings.ENVIRONMENT, "staging")
            self.assertEqual(settings.PORT, 9090)
            self.assertTrue(settings.DEBUG)

    def test_get_settings_cached_instance(self):
        s1 = get_settings()
        s2 = get_settings()
        self.assertIs(s1, s2)


if __name__ == "__main__":
    unittest.main()
