"""Authentication, JWT token lifecycle, and role-based authorization security engine.

Provides bcrypt password hashing, HS256 signed JSON Web Tokens (Access and Refresh),
deterministic SHA-256 API key hashing, and FastAPI dependency injectors for RBAC protection.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.exceptions import (
    InsufficientPermissionsError,
    InvalidCredentialsError,
    TokenExpiredError,
)
from src.core.logger import get_logger
from src.database import get_db_session
from src.models.audit import ApiKey
from src.models.user import User, UserRole

logger = get_logger(__name__)
settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ============================================================================
# Password Hashing & Verification
# ============================================================================


def hash_password(password: str) -> str:
    """Hashes a plaintext password using bcrypt with standard salt rounds."""
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plaintext password against a stored bcrypt hash in constant time."""
    try:
        password_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except Exception as exc:
        logger.warning("Password verification failed with error", extra={"error": str(exc)})
        return False


# ============================================================================
# JWT Token Generation & Verification
# ============================================================================


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    claims: dict[str, Any] | None = None,
) -> str:
    """Creates a signed JWT access token for user authentication."""
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    if claims:
        payload.update(claims)

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Creates a signed JWT refresh token for session continuation."""
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decodes, verifies signature, and checks expiration of a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        token_type = payload.get("type")
        if token_type != expected_type:
            raise InvalidCredentialsError(
                f"Invalid token type: expected '{expected_type}', got '{token_type}'."
            )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired. Please authenticate again.") from exc
    except (JWTError, Exception) as exc:
        raise InvalidCredentialsError("Could not validate credentials.") from exc


# ============================================================================
# API Key Management
# ============================================================================


def generate_api_key(name: str, prefix_len: int = 8) -> tuple[str, str, str]:
    """Generates a secure programmatic API key.

    Returns:
        tuple[raw_key, key_hash, prefix]:
            - raw_key: Key provided ONCE to the user (e.g. cwo_live_a1b2c3d4_...).
            - key_hash: SHA-256 digest persisted in the database.
            - prefix: Short human-identifiable prefix stored in plain text.
    """
    random_part = secrets.token_hex(24)
    prefix = f"cwo_{secrets.token_hex(prefix_len // 2)}"
    raw_key = f"{prefix}_{random_part}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, key_hash, prefix


def hash_api_key(raw_key: str) -> str:
    """Calculates deterministic SHA-256 digest of an API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ============================================================================
# FastAPI Authentication & RBAC Dependencies
# ============================================================================


async def get_current_user(
    token: str | None = Security(oauth2_scheme),
    api_key: str | None = Security(api_key_header),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """FastAPI dependency resolving the authenticated User from JWT or API Key."""
    if not token and not api_key:
        raise InvalidCredentialsError("Authentication credentials (JWT or X-API-Key) missing.")

    # 1. Bearer JWT Authentication
    if token:
        payload = decode_token(token, expected_type="access")
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise InvalidCredentialsError("Token payload missing subject identifier.")

        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise InvalidCredentialsError("User associated with this token does not exist.")
        return user

    # 2. API Key Authentication
    if api_key:
        key_hash = hash_api_key(api_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        result = await session.execute(stmt)
        api_key_record = result.scalar_one_or_none()
        if not api_key_record:
            raise InvalidCredentialsError("Invalid or inactive API key.")

        # Update last_used_at timestamp
        api_key_record.last_used_at = datetime.now(UTC)
        await session.commit()

        # Load linked user
        user_stmt = select(User).where(User.id == api_key_record.user_id)
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if not user:
            raise InvalidCredentialsError("User associated with this API key no longer exists.")
        return user

    raise InvalidCredentialsError("Invalid authentication state.")


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency ensuring the authenticated user is currently active."""
    if not current_user.is_active:
        raise InsufficientPermissionsError("User account is disabled or deactivated.")
    return current_user


def require_role(*allowed_roles: UserRole | str):
    """Factory dependency enforcing Role-Based Access Control (RBAC)."""
    roles_set = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.is_superuser:
            return current_user
        if current_user.role not in roles_set:
            raise InsufficientPermissionsError(
                f"Role '{current_user.role}' does not have permission. Required: {sorted(roles_set)}"
            )
        return current_user

    return role_checker
