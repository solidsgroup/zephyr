from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import database_url_from_environment


class Base(DeclarativeBase):
    pass


database_url = database_url_from_environment()
engine = create_async_engine(database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


if database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def create_schema_for_development() -> None:
    """Create tables for SQLite/dev use; production uses Alembic."""
    if database_url.startswith("sqlite"):
        from . import models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
