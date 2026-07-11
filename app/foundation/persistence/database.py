"""SQLAlchemy engine, session factory and per-request session helpers.

Sync sessions back Session 6 ingestion paths. The embedding ingest endpoint
uses the async API (``asyncpg``) so a failed embedder call rolls back the
whole transaction without leaving orphan ``documents`` rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _async_database_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache
def create_engine_from_settings() -> Engine:
    """Build the global engine from ``Settings.DATABASE_URL`` (singleton)."""
    return create_engine(
        get_settings().DATABASE_URL,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def create_async_engine_from_settings() -> AsyncEngine:
    """Async engine for the embedding ingest path."""
    return create_async_engine(
        _async_database_url(get_settings().DATABASE_URL),
        pool_pre_ping=True,
        future=True,
    )


SessionLocal = sessionmaker(
    bind=create_engine_from_settings(),
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@lru_cache
def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    """Lazy factory — avoids importing ``asyncpg`` until the ingest path runs."""
    return async_sessionmaker(
        bind=create_async_engine_from_settings(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
        class_=AsyncSession,
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a Session and closes it on exit."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession and closes it on exit."""
    async with get_async_session_maker()() as session:
        yield session
