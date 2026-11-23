"""Unit tests for password hashing, JWT token lifecycle, API keys, and RBAC security."""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock

from src.core.exceptions import (
    InsufficientPermissionsError,
    InvalidCredentialsError,
    TokenExpiredError,
)
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    require_role,
    verify_password,
)
from src.models.user import User, UserRole


class TestSecurityEngine(unittest.TestCase):
    """Verifies that cryptographic hashing, token signing, and RBAC rules operate securely."""

    def test_password_hash_and_verify(self):
        plain_pw = "SuperSecretPassword123!"
        hashed_pw = hash_password(plain_pw)

        self.assertNotEqual(plain_pw, hashed_pw)
        self.assertTrue(verify_password(plain_pw, hashed_pw))
        self.assertFalse(verify_password("WrongPassword123!", hashed_pw))
        self.assertFalse(verify_password("", hashed_pw))

    def test_access_token_creation_and_decoding(self):
        user_id = "user-uuid-101"
        claims = {"email": "dev@company.com", "role": "OPERATOR"}
        token = create_access_token(subject=user_id, claims=claims)

        payload = decode_token(token, expected_type="access")
        self.assertEqual(payload["sub"], user_id)
        self.assertEqual(payload["email"], "dev@company.com")
        self.assertEqual(payload["role"], "OPERATOR")
        self.assertEqual(payload["type"], "access")

    def test_token_type_mismatch_raises(self):
        user_id = "user-uuid-102"
        token = create_access_token(subject=user_id)

        with self.assertRaises(InvalidCredentialsError):
            decode_token(token, expected_type="refresh")

    def test_expired_token_raises(self):
        user_id = "user-uuid-103"
        expired_token = create_access_token(subject=user_id, expires_delta=timedelta(seconds=-10))

        with self.assertRaises(TokenExpiredError):
            decode_token(expired_token, expected_type="access")

    def test_refresh_token_lifecycle(self):
        user_id = "user-uuid-104"
        refresh_token = create_refresh_token(subject=user_id)

        payload = decode_token(refresh_token, expected_type="refresh")
        self.assertEqual(payload["sub"], user_id)
        self.assertEqual(payload["type"], "refresh")

    def test_api_key_generation_and_hashing(self):
        raw_key, key_hash, prefix = generate_api_key(name="CI Runner")

        self.assertTrue(raw_key.startswith("cwo_"))
        self.assertIn(prefix, raw_key)
        self.assertEqual(len(key_hash), 64)  # SHA-256 hex length
        self.assertEqual(hash_api_key(raw_key), key_hash)

    def test_rbac_require_role_decorator(self):
        checker = require_role(UserRole.ADMIN, UserRole.OPERATOR)

        # 1. Operator user should pass
        operator_user = MagicMock(spec=User)
        operator_user.role = UserRole.OPERATOR.value
        operator_user.is_superuser = False
        operator_user.is_active = True

        import asyncio

        res = asyncio.run(checker(current_user=operator_user))
        self.assertEqual(res, operator_user)

        # 2. Viewer user should fail
        viewer_user = MagicMock(spec=User)
        viewer_user.role = UserRole.VIEWER.value
        viewer_user.is_superuser = False
        viewer_user.is_active = True

        with self.assertRaises(InsufficientPermissionsError):
            asyncio.run(checker(current_user=viewer_user))

        # 3. Superuser should always pass
        superuser = MagicMock(spec=User)
        superuser.role = "CUSTOM_ROLE"
        superuser.is_superuser = True
        superuser.is_active = True

        res_su = asyncio.run(checker(current_user=superuser))
        self.assertEqual(res_su, superuser)


if __name__ == "__main__":
    unittest.main()
