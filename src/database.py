"""Asynchronous database engine, connection pool, and session lifecycle management.

Configured with SQLAlchemy 2.0 DeclarativeBase, connection pooling with overflow,
and async session generator dependencies for FastAPI and background workers.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import get_settings
from src.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""

    pass


def get_engine(database_url: str = settings.DATABASE_URL) -> AsyncEngine:
    """Builds and returns a configured AsyncEngine instance."""
    # SQLite in-memory or file does not support pool_size / max_overflow
    if "sqlite" in database_url:
        return create_async_engine(
            database_url,
            echo=settings.DEBUG,
            future=True,
        )

    return create_async_engine(
        database_url,
        echo=settings.DEBUG,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,  # Automatically verify connection vitality before checkout
        future=True,
    )


# Application-wide singleton engine & sessionmaker
engine: AsyncEngine = get_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an isolated async database session with automatic commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("Database transaction rolled back due to error", extra={"error": str(exc)})
            raise
        finally:
            await session.close()


async def check_db_health(
    custom_sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Probes database connection to verify connectivity and health."""
    session_factory = custom_sessionmaker or AsyncSessionLocal
    try:
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as exc:
        logger.warning("Database health check probe failed", extra={"error": str(exc)})
        return False


async def init_models(custom_engine: AsyncEngine = engine) -> None:
    """Creates all registered database tables (intended for development & test fixtures)."""
    async with custom_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_models(custom_engine: AsyncEngine = engine) -> None:
    """Drops all registered database tables (intended for test tear-down)."""
    async with custom_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
