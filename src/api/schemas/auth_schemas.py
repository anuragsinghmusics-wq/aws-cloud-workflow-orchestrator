"""Pydantic v2 schemas for authentication, token exchange, user management, and API keys."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.user import UserRole

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"


class UserRegisterRequest(BaseModel):
    """Payload for registering a new user account."""

    email: str = Field(..., pattern=EMAIL_REGEX, description="Unique email address")
    password: str = Field(..., min_length=8, max_length=72, description="Plaintext password")
    full_name: str | None = Field(default=None, max_length=255, description="Full display name")
    role: UserRole = Field(default=UserRole.OPERATOR, description="Assigned RBAC role")


class UserLoginRequest(BaseModel):
    """Payload for password-based authentication."""

    email: str = Field(..., pattern=EMAIL_REGEX, description="Registered email address")
    password: str = Field(..., description="Plaintext password")


class TokenResponse(BaseModel):
    """Bearer token pair returned upon successful authentication or refresh."""

    access_token: str = Field(..., description="Signed HS256 JWT access token")
    refresh_token: str = Field(..., description="Signed HS256 JWT refresh token")
    token_type: str = Field(default="bearer", description="Token scheme identifier")
    expires_in: int = Field(..., description="Access token expiration window in seconds")


class TokenRefreshRequest(BaseModel):
    """Payload to exchange a refresh token for a fresh access token."""

    refresh_token: str = Field(..., description="Valid JWT refresh token")


class UserResponse(BaseModel):
    """Public user identity representation."""

    id: str = Field(..., description="User unique identifier (UUID)")
    email: str = Field(..., description="User email address")
    full_name: str | None = Field(default=None, description="Full display name")
    role: str = Field(..., description="Assigned RBAC role")
    is_active: bool = Field(..., description="Whether account is active")
    is_superuser: bool = Field(..., description="Superuser administrative status")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateRequest(BaseModel):
    """Payload to generate a new machine-to-machine API key."""

    name: str = Field(
        ..., min_length=3, max_length=100, description="Friendly identifier for the key"
    )


class ApiKeyCreatedResponse(BaseModel):
    """API key response including the raw secret (shown once only)."""

    id: str = Field(..., description="API key record UUID")
    name: str = Field(..., description="Friendly identifier")
    prefix: str = Field(..., description="Key prefix for identification")
    raw_key: str = Field(
        ...,
        description="Full plaintext API key. Store securely -- this key cannot be recovered!",
    )
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class ApiKeyResponse(BaseModel):
    """Public representation of a stored API key without sensitive secret."""

    id: str = Field(..., description="API key record UUID")
    name: str = Field(..., description="Friendly identifier")
    prefix: str = Field(..., description="Key prefix")
    is_active: bool = Field(..., description="Active status")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_used_at: datetime | None = Field(default=None, description="Last access timestamp")

    model_config = ConfigDict(from_attributes=True)
