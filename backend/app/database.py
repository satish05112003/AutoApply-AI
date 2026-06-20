import asyncio
import os
import weakref
from collections.abc import AsyncGenerator
import sqlalchemy
from datetime import datetime, timezone

_OriginalDateTime = sqlalchemy.DateTime

class UTCDateTime(sqlalchemy.types.TypeDecorator):
    impl = _OriginalDateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

# Apply patch globally before any models are imported
sqlalchemy.DateTime = UTCDateTime
sqlalchemy.types.DateTime = UTCDateTime
sqlalchemy.sql.sqltypes.DateTime = UTCDateTime

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.config import settings

# Global registries for loop-bound engines
_engines = weakref.WeakKeyDictionary()
_default_engine = None

def get_engine():
    global _default_engine
    
    # Use NullPool for unit tests
    if os.getenv("PYTEST_CURRENT_TEST"):
        if _default_engine is None:
            _default_engine = create_async_engine(
                settings.DATABASE_URL,
                poolclass=NullPool,
                echo=False,
                connect_args={"server_settings": {"timezone": "utc"}},
            )
        return _default_engine

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Fallback if no event loop is running (e.g. startup, import time, or sync scripts)
        if _default_engine is None:
            _default_engine = create_async_engine(
                settings.DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=20,
                max_overflow=40,
                echo=False,
                connect_args={"server_settings": {"timezone": "utc"}},
            )
        return _default_engine

    if loop not in _engines:
        engine = create_async_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=20,
            max_overflow=40,
            echo=False,
            connect_args={"server_settings": {"timezone": "utc"}},
        )
        _engines[loop] = engine
        
    return _engines[loop]


class LoopBoundSessionMaker:
    """A sessionmaker proxy that dynamically binds to the active event loop's engine."""
    def __call__(self) -> AsyncSession:
        engine = get_engine()
        maker = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False
        )
        return maker()

# SessionLocal callable proxy
SessionLocal = LoopBoundSessionMaker()

# Declarative Base
class Base(DeclarativeBase):
    pass

# FastAPI Dependency for obtaining an async session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Dependency yielding database sessions
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def close_current_loop_engine():
    """Dispose of the database engine and close all pool connections for the current event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop in _engines:
        engine = _engines.pop(loop)
        try:
            await engine.dispose()
        except Exception:
            pass

