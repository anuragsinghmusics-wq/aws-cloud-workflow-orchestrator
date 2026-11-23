"""Integration tests for user registration, authentication, token rotation, and API key management."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.core.security import create_access_token, create_refresh_token, hash_password
from src.database import get_db_session
from src.main import app
from src.models.audit import ApiKey
from src.models.user import User, UserRole


class TestAuthAPI(unittest.TestCase):
    """Verifies that authentication, JWT issuance, profile inspection, and API keys operate securely."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        # Mock session generator
        async def override_db():
            yield self.mock_session

        app.dependency_overrides[get_db_session] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_register_user_success(self):
        # Setup: user does not exist
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.mock_session.execute.return_value = mock_result

        payload = {
            "email": "engineer@company.com",
            "password": "StrongPassword123!",
            "full_name": "Dev Engineer",
            "role": "OPERATOR",
        }
        response = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["email"], "engineer@company.com")
        self.assertEqual(data["role"], "OPERATOR")
        self.assertTrue(data["is_active"])
        self.mock_session.commit.assert_awaited()

    def test_register_duplicate_user_raises_409(self):
        # Setup: user already exists
        existing_user = User(
            email="existing@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        self.mock_session.execute.return_value = mock_result

        payload = {
            "email": "existing@company.com",
            "password": "StrongPassword123!",
            "full_name": "Existing User",
            "role": "OPERATOR",
        }
        response = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["error"], "ERR_AUTH_USER_ALREADY_EXISTS")

    def test_login_success(self):
        pw = "MySecretPassword123!"
        hashed = hash_password(pw)
        user = User(
            email="login@company.com",
            hashed_password=hashed,
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_result

        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "login@company.com", "password": pw},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "bearer")

    def test_login_invalid_password_raises_401(self):
        user = User(
            email="login@company.com",
            hashed_password=hash_password("CorrectPassword"),
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_result

        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "login@company.com", "password": "WrongPassword"},
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["error"], "ERR_AUTH_INVALID_CREDENTIALS")

    def test_refresh_token_success(self):
        user = User(
            email="refresh@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )
        refresh_token = create_refresh_token(subject=user.id)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_result

        response = self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

    def test_get_current_user_profile(self):
        user = User(
            email="me@company.com",
            hashed_password="hash",
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        token = create_access_token(subject=user.id)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_result

        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["email"], "me@company.com")
        self.assertEqual(data["role"], "ADMIN")

    def test_create_and_list_api_keys(self):
        user = User(
            email="apikey_owner@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )
        token = create_access_token(subject=user.id)

        # Setup mock for user retrieval during get_current_user
        mock_user_res = MagicMock()
        mock_user_res.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_user_res

        # 1. Create API Key
        create_res = self.client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Jenkins Deployment Runner"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(create_res.status_code, 201)
        created_data = create_res.json()
        self.assertEqual(created_data["name"], "Jenkins Deployment Runner")
        self.assertTrue(created_data["raw_key"].startswith("cwo_"))

        # 2. List API Keys
        existing_key = ApiKey(
            name="Jenkins Deployment Runner",
            key_hash="hash",
            prefix=created_data["prefix"],
            user_id=user.id,
        )
        mock_list_res = MagicMock()
        mock_list_res.scalars.return_value.all.return_value = [existing_key]
        mock_list_res.scalar_one_or_none.return_value = user
        self.mock_session.execute.return_value = mock_list_res

        list_res = self.client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(list_res.status_code, 200)
        keys = list_res.json()
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["prefix"], created_data["prefix"])


if __name__ == "__main__":
    unittest.main()
