"""
app/database.py
SQLAlchemy async engine + session factory.
Supports SQLite (dev) and PostgreSQL (prod) via DATABASE_URL.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# ── Engine ─────────────────────────────────────────────────────────────────────
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    connect_args=connect_args,
)

# ── Session factory ────────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Base ───────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Dependency ─────────────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Init DB (create tables) ────────────────────────────────────────────────────
async def init_db() -> None:
    """Create all tables if they don't exist (dev convenience)."""
    from app.models import linkedin_prospect  # noqa: F401 — registers models
    from app.models import pipeline_run       # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
