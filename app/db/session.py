from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().db_url(), pool_pre_ping=True, connect_args={"timeout": 5})


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    request.state.session_factory = get_session_factory()
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
