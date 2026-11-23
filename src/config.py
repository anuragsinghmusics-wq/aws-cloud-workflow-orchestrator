"""Application Configuration and Environment Settings.

Provides centralized, type-safe configuration with support for environment files (.env),
LocalStack endpoint overrides, database connection pooling, and AWS service settings.
Compatible with Pydantic v2 Settings.
"""

import os
from functools import lru_cache

# Load dotenv if available
try:
    from dotenv import load_dotenv

    # Load environment file if present: preference .env -> .env.development
    if os.path.exists(".env"):
        load_dotenv(".env")
    elif os.path.exists(".env.development"):
        load_dotenv(".env.development")
except ImportError:
    pass

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    HAS_PYDANTIC_SETTINGS = True
except ImportError:
    from pydantic import BaseModel as BaseSettings  # type: ignore
    from pydantic import Field

    SettingsConfigDict = None  # type: ignore
    HAS_PYDANTIC_SETTINGS = False


class Settings(BaseSettings):
    """Central configuration for AWS Cloud Workflow Orchestrator."""

    if HAS_PYDANTIC_SETTINGS:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
            case_sensitive=False,
        )

    # ------------------------------------------------------------------------
    # Application & Environment
    # ------------------------------------------------------------------------
    ENVIRONMENT: str = Field(
        default="development", description="Environment: development, test, staging, production"
    )
    PROJECT_NAME: str = Field(
        default="AWS Cloud-Native Workflow Orchestrator", description="Application name"
    )
    VERSION: str = Field(default="0.1.0", description="API version")
    DEBUG: bool = Field(default=False, description="Debug mode")
    API_V1_PREFIX: str = Field(default="/api/v1", description="REST API v1 routing prefix")
    HOST: str = Field(default="0.0.0.0", description="API bind host")  # nosec B104
    PORT: int = Field(default=8000, description="API bind port")
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins for admin dashboard",
    )

    # ------------------------------------------------------------------------
    # Logging & Observability
    # ------------------------------------------------------------------------
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")
    LOG_JSON_FORMAT: bool = Field(default=True, description="Output structured JSON logs")

    # ------------------------------------------------------------------------
    # AWS Core & LocalStack Simulation
    # ------------------------------------------------------------------------
    AWS_REGION: str = Field(default="us-east-1", description="Primary AWS region")
    AWS_ACCESS_KEY_ID: str = Field(
        default="test", description="AWS access key (mock for LocalStack)"
    )
    AWS_SECRET_ACCESS_KEY: str = Field(
        default="test", description="AWS secret key (mock for LocalStack)"
    )
    USE_LOCALSTACK: bool = Field(
        default=True, description="Use LocalStack for local AWS service emulation"
    )
    LOCALSTACK_ENDPOINT_URL: str = Field(
        default="http://localhost:4566", description="LocalStack edge endpoint"
    )

    # AWS S3 Settings
    S3_ENDPOINT_URL: str | None = Field(
        default=None,
        description="Explicit S3 endpoint override (defaults to LocalStack when USE_LOCALSTACK=True)",
    )
    S3_BUCKET_NAME: str = Field(
        default="cloud-orchestrator-payload-staging",
        description="S3 bucket for migration payload snapshots",
    )
    S3_STAGING_PREFIX: str = Field(default="payloads", description="Prefix path within S3 bucket")
    S3_MULTIPART_THRESHOLD_MB: int = Field(
        default=5, description="File size in MB to trigger multipart upload"
    )

    # Amazon DynamoDB Settings
    DYNAMODB_ENDPOINT_URL: str | None = Field(
        default=None,
        description="Explicit DynamoDB endpoint override (defaults to LocalStack if USE_LOCALSTACK=True)",
    )
    DYNAMODB_STATE_TABLE: str = Field(
        default="Orchestrator_Workflow_Ledger",
        description="DynamoDB table name for workflow state & audit trail",
    )
    DYNAMODB_DEFAULT_TARGET_TABLE: str = Field(
        default="Migrated_Production_Records",
        description="Default destination table for migrated records",
    )
    DYNAMODB_MAX_BATCH_SIZE: int = Field(
        default=25, description="Maximum items per batch write call (DynamoDB limit is 25)"
    )

    # Amazon CloudWatch Settings
    CLOUDWATCH_ENDPOINT_URL: str | None = Field(
        default=None, description="Explicit CloudWatch endpoint override"
    )
    CLOUDWATCH_NAMESPACE: str = Field(
        default="CloudWorkflowOrchestrator", description="CloudWatch custom metrics namespace"
    )
    CLOUDWATCH_LOG_GROUP: str = Field(
        default="/aws/orchestrator/workflows",
        description="CloudWatch log group for task audit logs",
    )

    # ------------------------------------------------------------------------
    # Relational Database (PostgreSQL for metadata, users, audit)
    # ------------------------------------------------------------------------
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/orchestrator_db",
        description="SQLAlchemy async database connection URL",
    )
    DB_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, description="Database max overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Connection pool timeout in seconds")

    # ------------------------------------------------------------------------
    # Redis & Celery Distributed Task Queue
    # ------------------------------------------------------------------------
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1", description="Celery message broker URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2", description="Celery task result backend URL"
    )
    CELERY_TASK_DEFAULT_QUEUE: str = Field(
        default="orchestrator_tasks", description="Default queue name"
    )
    CELERY_TASK_TIME_LIMIT: int = Field(
        default=1800, description="Hard task timeout in seconds (30 minutes)"
    )

    # ------------------------------------------------------------------------
    # Worker Concurrency & Resilience
    # ------------------------------------------------------------------------
    WORKER_CONCURRENCY: int = Field(
        default=4, description="Worker thread / process pool concurrency"
    )
    MAX_RETRIES: int = Field(default=3, description="Default max retries for transient failures")
    RETRY_BASE_DELAY: float = Field(default=0.5, description="Initial retry delay in seconds")
    RETRY_MAX_DELAY: float = Field(
        default=30.0, description="Maximum retry backoff delay in seconds"
    )
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(
        default=5, description="Consecutive errors to trigger circuit breaker OPEN"
    )
    CIRCUIT_BREAKER_RESET_TIMEOUT: float = Field(
        default=30.0, description="Seconds before half-open circuit breaker probe"
    )

    # ------------------------------------------------------------------------
    # Security & Authentication
    # ------------------------------------------------------------------------
    JWT_SECRET_KEY: str = Field(
        default="insecure-dev-secret-change-in-production-09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
        description="Secret key for signing JWT tokens",
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, description="JWT access token expiry in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="JWT refresh token expiry in days"
    )

    def __init__(self, **kwargs: object) -> None:
        # If running without pydantic-settings, load environment variables manually
        if not HAS_PYDANTIC_SETTINGS and not kwargs:
            env_kwargs = {}
            for field_name, field_info in self.__class__.model_fields.items():
                env_val = os.getenv(field_name.upper()) or os.getenv(field_name.lower())
                if env_val is not None:
                    # Type casting for bool, int, float, list
                    annotation = field_info.annotation
                    if annotation is bool:
                        env_kwargs[field_name] = env_val.lower() in ("true", "1", "yes")
                    elif annotation is int:
                        env_kwargs[field_name] = int(env_val)
                    elif annotation is float:
                        env_kwargs[field_name] = float(env_val)
                    else:
                        env_kwargs[field_name] = env_val
            kwargs.update(env_kwargs)
        super().__init__(**kwargs)

    @property
    def effective_s3_endpoint(self) -> str | None:
        """Resolves the active S3 endpoint (LocalStack if enabled and override not set)."""
        if self.S3_ENDPOINT_URL:
            return self.S3_ENDPOINT_URL
        return self.LOCALSTACK_ENDPOINT_URL if self.USE_LOCALSTACK else None

    @property
    def effective_dynamodb_endpoint(self) -> str | None:
        """Resolves the active DynamoDB endpoint (LocalStack if enabled and override not set)."""
        if self.DYNAMODB_ENDPOINT_URL:
            return self.DYNAMODB_ENDPOINT_URL
        return self.LOCALSTACK_ENDPOINT_URL if self.USE_LOCALSTACK else None

    @property
    def effective_cloudwatch_endpoint(self) -> str | None:
        """Resolves the active CloudWatch endpoint (LocalStack if enabled and override not set)."""
        if self.CLOUDWATCH_ENDPOINT_URL:
            return self.CLOUDWATCH_ENDPOINT_URL
        return self.LOCALSTACK_ENDPOINT_URL if self.USE_LOCALSTACK else None

    @property
    def is_production(self) -> bool:
        """Helper to check if running in production mode."""
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Returns a cached, singleton instance of the application settings."""
    return Settings()
