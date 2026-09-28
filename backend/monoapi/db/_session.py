import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Generator

from pydantic import PostgresDsn
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from monoapi.core import settings

logger = logging.getLogger(__name__)


class AsyncSessionManager:
    def __init__(  # noqa: PLR0913
        self,
        /,
        *,
        host: str,
        pool_max_overflow: int,
        pool_size: int,
        pool_timeout: int,
        pool_recycle: int,
        echo: bool = False,
        autocommit: bool = False,
        expire_on_commit: bool = False,
    ) -> None:
        self.async_engine: AsyncEngine = create_async_engine(
            str(host),
            echo=echo,
            max_overflow=pool_max_overflow,
            pool_size=pool_size,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )

        self._async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            autocommit=autocommit,
            bind=self.async_engine,
            expire_on_commit=expire_on_commit,
        )
        self._is_closed: bool = False

    async def close(self) -> None:
        if self._is_closed:
            raise RuntimeError("SessionManager has been closed.")

        await self.async_engine.dispose()

        self._is_closed = True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._is_closed:
            raise RuntimeError("SessionManager has been closed.")

        session = self._async_session_maker()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async_session_manager: AsyncSessionManager = AsyncSessionManager(host=settings.db.db_async_url,
                                                 pool_max_overflow=settings.db_session.pool_max_overflow,
                                                 pool_size=settings.db_session.pool_size,
                                                 pool_timeout=settings.db_session.pool_timeout,
                                                 pool_recycle=settings.db_session.pool_recycle,
                                                 echo=settings.db_session.echo)


async def get_async_session():
    async with async_session_manager.session() as session:
        yield session