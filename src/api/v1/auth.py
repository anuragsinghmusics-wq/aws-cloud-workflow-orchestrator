"""Authentication, token rotation, user profile, and API key management routes."""

import importlib.util
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.auth_schemas import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    TokenRefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from src.config import get_settings
from src.core.exceptions import (
    InvalidCredentialsError,
    ResourceNotFoundError,
    UserAlreadyExistsError,
)
from src.core.logger import get_logger
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_current_active_user,
    hash_password,
    verify_password,
)
from src.database import get_db_session
from src.models.audit import ApiKey, AuditLog
from src.models.user import User

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register_user(
    req: UserRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Creates a new user profile with a bcrypt-hashed password and assigned RBAC role."""
    # Check if user already exists
    stmt = select(User).where(User.email == req.email.lower())
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise UserAlreadyExistsError(f"A user with email '{req.email}' is already registered.")

    hashed_pw = hash_password(req.password)
    user = User(
        email=req.email.lower(),
        hashed_password=hashed_pw,
        full_name=req.full_name,
        role=req.role.value if hasattr(req.role, "value") else str(req.role),
        is_active=True,
    )
    session.add(user)

    audit = AuditLog(
        entity_type="user",
        entity_id=user.id,
        action="REGISTER",
        details={"email": user.email, "role": user.role},
        user_id=user.id,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(user)

    logger.info("New user registered successfully", extra={"user_id": user.id, "email": user.email})
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive JWT token pair",
)
async def login(
    req: UserLoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Validates user credentials and issues short-lived Access and long-lived Refresh JWTs."""
    stmt = select(User).where(User.email == req.email.lower())
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise InvalidCredentialsError("Invalid email address or password provided.")

    if not user.is_active:
        raise InvalidCredentialsError("User account is inactive or disabled.")

    access_token = create_access_token(
        subject=user.id,
        claims={"email": user.email, "role": user.role},
    )
    refresh_token = create_refresh_token(subject=user.id)

    logger.info("User logged in successfully", extra={"user_id": user.id, "email": user.email})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",  # nosec B106
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


HAS_MULTIPART = importlib.util.find_spec("multipart") is not None

if HAS_MULTIPART:

    @router.post(
        "/oauth2-token",
        response_model=TokenResponse,
        include_in_schema=False,
    )
    async def login_oauth2(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        session: AsyncSession = Depends(get_db_session),
    ) -> TokenResponse:
        """OAuth2 password form compatible endpoint for Swagger UI authorization."""
        return await login(
            UserLoginRequest(email=form_data.username, password=form_data.password),
            session=session,
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate tokens using a valid refresh token",
)
async def refresh_tokens(
    req: TokenRefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Validates an unexpired refresh token and returns a fresh access token."""
    payload = decode_token(req.refresh_token, expected_type="refresh")
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidCredentialsError("Malformed refresh token subject.")

    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise InvalidCredentialsError("User account associated with refresh token is invalid.")

    new_access_token = create_access_token(
        subject=user.id,
        claims={"email": user.email, "role": user.role},
    )
    new_refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",  # nosec B106
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Returns profile attributes of the currently authenticated caller."""
    return current_user


@router.post(
    "/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a machine-to-machine API key",
)
async def create_user_api_key(
    req: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiKeyCreatedResponse:
    """Creates a secure API key for programmatic automation. The plaintext key is only returned once."""
    raw_key, key_hash, prefix = generate_api_key(name=req.name)

    api_key_record = ApiKey(
        name=req.name,
        key_hash=key_hash,
        prefix=prefix,
        user_id=current_user.id,
        is_active=True,
    )
    session.add(api_key_record)

    audit = AuditLog(
        entity_type="api_key",
        entity_id=api_key_record.id,
        action="CREATE_API_KEY",
        details={"name": req.name, "prefix": prefix},
        user_id=current_user.id,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(api_key_record)

    logger.info("API key generated", extra={"user_id": current_user.id, "prefix": prefix})
    return ApiKeyCreatedResponse(
        id=api_key_record.id,
        name=api_key_record.name,
        prefix=api_key_record.prefix,
        raw_key=raw_key,
        created_at=api_key_record.created_at,
    )


@router.get(
    "/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List active API keys for caller",
)
async def list_user_api_keys(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApiKey]:
    """Retrieves all API keys issued to the current user."""
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id, ApiKey.is_active.is_(True))
        .order_by(ApiKey.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Deactivates an API key, preventing any further authentication."""
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    result = await session.execute(stmt)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise ResourceNotFoundError(f"API key with ID '{key_id}' was not found.")

    key_record.is_active = False
    audit = AuditLog(
        entity_type="api_key",
        entity_id=key_record.id,
        action="REVOKE_API_KEY",
        details={"name": key_record.name, "prefix": key_record.prefix},
        user_id=current_user.id,
    )
    session.add(audit)
    await session.commit()
    logger.info("API key revoked", extra={"key_id": key_id, "user_id": current_user.id})
