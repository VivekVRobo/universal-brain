"""
Universal Brain - Database Engine & Connection Lifecycle Manager

Implements M6 Sections 37-43, 58-63:
Asynchronous SQLAlchemy 2.0 engine and session factory supporting bounded pooling,
health diagnostics, and backend portability (PostgreSQL asyncpg / SQLite WAL aiosqlite).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from universal_brain.config import settings
from universal_brain.persistence.errors import (
    DatabaseUnavailableError,
    PersistenceTimeoutError,
)
from universal_brain.persistence.models import Base


class DatabaseManager:
    """Manages AsyncEngine lifecycle, connection pooling, and session factories."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: float = 30.0,
        pool_recycle: int = 1800,
    ) -> None:
        self.url = database_url or settings.database_url
        self.echo = echo
        self._is_sqlite = "sqlite" in self.url

        # Configure Engine
        engine_kwargs: Dict[str, Any] = {"echo": self.echo}
        if self._is_sqlite:
            # SQLite does not use QueuePool overflow, uses NullPool or StaticPool
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs.update({
                "poolclass": AsyncAdaptedQueuePool,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout,
                "pool_recycle": pool_recycle,
            })

        self.engine: AsyncEngine = create_async_engine(self.url, **engine_kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    async def init_db(self) -> None:
        """Initializes connection settings, pragmas, and checks connectivity."""
        try:
            async with self.engine.begin() as conn:
                if self._is_sqlite:
                    await conn.execute(text("PRAGMA journal_mode=WAL;"))
                    await conn.execute(text("PRAGMA foreign_keys=ON;"))
                else:
                    await conn.execute(text("SELECT 1;"))
        except Exception as e:
            raise DatabaseUnavailableError(f"Failed to connect to database at '{self.url}': {e}") from e

    async def create_tables(self) -> None:
        """Creates all registered ORM tables in the database."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as e:
            raise DatabaseUnavailableError(f"Failed to create database schema: {e}") from e

    async def drop_tables(self) -> None:
        """Drops all registered tables (used for test teardown)."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        except Exception as e:
            raise DatabaseUnavailableError(f"Failed to drop database schema: {e}") from e

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provides an isolated AsyncSession context."""
        session = self.session_factory()
        try:
            yield session
        except asyncio.TimeoutError as e:
            await session.rollback()
            raise PersistenceTimeoutError(f"Database session operation timed out: {e}") from e
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def health_check(self) -> Dict[str, Any]:
        """Executes a liveness check and returns connection pool telemetry."""
        try:
            async with self.engine.connect() as conn:
                start = asyncio.get_event_loop().time()
                await conn.execute(text("SELECT 1;"))
                latency_ms = round((asyncio.get_event_loop().time() - start) * 1000, 2)

            return {
                "status": "HEALTHY",
                "backend": "sqlite" if self._is_sqlite else "postgresql",
                "latency_ms": latency_ms,
                "pool_size": getattr(self.engine.pool, "size", lambda: 0)(),
                "checked_in": getattr(self.engine.pool, "checkedin", lambda: 0)(),
                "checked_out": getattr(self.engine.pool, "checkedout", lambda: 0)(),
            }
        except Exception as e:
            return {
                "status": "UNHEALTHY",
                "backend": "sqlite" if self._is_sqlite else "postgresql",
                "error": str(e),
            }

    async def close(self) -> None:
        """Disposes the engine connection pool."""
        await self.engine.dispose()
