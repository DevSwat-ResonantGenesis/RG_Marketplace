"""Database configuration for Marketplace service."""

import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

DB_POOL_SIZE = int(os.getenv("MARKETPLACE_DB_POOL_SIZE", "1"))
DB_MAX_OVERFLOW = int(os.getenv("MARKETPLACE_DB_MAX_OVERFLOW", "0"))
DB_POOL_TIMEOUT = int(os.getenv("MARKETPLACE_DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("MARKETPLACE_DB_POOL_RECYCLE", "1800"))
DB_POOL_CLASS = (os.getenv("MARKETPLACE_DB_POOL_CLASS", "queue").strip().lower() or "queue")

_engine_kwargs = {
    "echo": False,
}

if DB_POOL_CLASS in ("null", "none"):
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        {
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_timeout": DB_POOL_TIMEOUT,
            "pool_recycle": DB_POOL_RECYCLE,
            "pool_pre_ping": True,
            "pool_use_lifo": True,
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
