from typing import Any, Callable, Generator
from contextlib import asynccontextmanager
import logging

from sqlalchemy import text

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from monoapi.core import settings
from monoapi.db import async_session_manager, redis_session_manager


from monoapi.helpers.logger import get_logger

app_logger = get_logger(__name__)

class MonoAPI(FastAPI):
    """
    MonoAPI - это основной класс приложения, который наследуется от FastAPI. 
    Он настраивает жизненный цикл приложения, подключение к базе данных и Redis, 
    а также монтирует статические файлы и настраивает маршруты и промежуточные слои (middlewares).

    __init__ -> app
    """
    def __init__(self, **kwargs):
        super().__init__(lifespan=self.lifespan, **kwargs)

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Проверка подключения к БД
        try:
            async with async_session_manager.session() as session:
                await session.execute(text('SELECT 1'))
            app_logger.info("DB connected")
        except Exception as e:
            app_logger.error(f"DB connection failed: {e}")
            raise

        # Проверка подключения к Redis
        try:
            async with redis_session_manager.get_client() as client:
                await client.ping()
            app_logger.info("Redis connected")
        except Exception as e:
            app_logger.error(f"Redis connection failed: {e}")
            raise

        app_logger.info("API starts!")
        yield
        app_logger.info("API dead!")
        await async_session_manager.close()

    def _setup_middlewares(self) -> None:
        self.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routers(self) -> None:
        from monoapi.auth import auth_router
        from monoapi.routers import api_router
        
        for router in [auth_router, api_router]:
            self.include_router(router)

    def setup(self) -> None:
        super().setup()
        self._setup_middlewares()
        self._setup_routers()
        add_pagination(self)

api: MonoAPI = MonoAPI()
