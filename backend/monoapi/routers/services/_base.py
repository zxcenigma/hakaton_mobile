import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, TypeVar, AsyncGenerator
from uuid import UUID

from itsdangerous import URLSafeSerializer
from fastapi_pagination import Page
from fastapi import HTTPException, status
from jwt import ExpiredSignatureError, InvalidSignatureError, InvalidTokenError
from sqlalchemy import Select, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from redis import Redis

from monoapi.db.models import UserModel
from monoapi.db import (
    async_session_manager, 
    redis_session_manager
)
from monoapi.helpers.logger import get_logger
from monoapi.helpers.pydantic import BaseModel
from monoapi.auth.utils import decode_jwt
from monoapi.core import settings
from monoapi.utils import json_helper

service_wrapper_logger = get_logger(__name__)

TResponse = TypeVar(
    "TResponse",
    bound=BaseModel | Sequence[BaseModel] | Page[BaseModel] | None,
)


class ServiceError(Exception):
    """Service Error."""


class UnauthorizedError(ServiceError):
    """Unauthorized Error."""


class NotFoundError(ServiceError):
    """Not Found Error."""


class ConflictError(ServiceError):
    """Conflict Error."""


class RegistrationDisabledError(ServiceError):
    """Registration Disabled Error."""


class ValidationError(ServiceError):
    """Validation Error."""


class EmptyUpdateError(ValidationError):
    """Empty Update Error."""


class UserDeletionDisabledError(ServiceError):
    """User Deletion Disabled Error."""


class BaseService[TResponse](BaseModel, ABC):
    """Base interface for async application services."""

    context: dict[str, Any] | None = None

    @abstractmethod
    async def __call__(self, *args, **kwargs) -> TResponse:
        """Execute service logic."""


class BaseSessionService[TResponse](BaseService[TResponse], ABC):
    """Base service with managed database session."""

    def __init__(self, /, **data: Any) -> None:
        super().__init__(**data)

        self._redis_session: AsyncGenerator[Redis] | None = None
        self._session: AsyncSession | None = None

    @property
    def async_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Session is not initialized")

        return self._session
    
    @property
    def redis_session(self) -> Redis:
        if self._redis_session is None:
            raise RuntimeError("Redis session is not initialized")
        return self._redis_session

    @abstractmethod
    async def process(self, *args, **kwargs) -> TResponse:
        """
        Execute the main logic of the service.

        A database session is available via ``self.session``.
        """

    async def __call__(self, *args, **kwargs) -> TResponse:
        async with async_session_manager.session() as session:
            self._session = session
            async with redis_session_manager.get_client() as redis_session:
                self._redis_session = redis_session

                return await self.process(*args, **kwargs)


class BaseUserAuthenticatedService[TResponse](BaseSessionService[TResponse], ABC):
    """Base service with an authenticated user available via ``self.user``."""

    token: str

    def __init__(self, /, **data: Any) -> None:
        super().__init__(**data)

        self._user: UserModel | None = None

    @property
    def user(self) -> UserModel:
        if self._user is None:
            raise RuntimeError("User is not initialized")

        return self._user

    def ensure_access(self) -> None:
        if not self.user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь деактивирован",
            )

    def __get_decoded_token(self) -> dict[str, Any]:
        try:
            decoded_token: dict[str, Any] = decode_jwt(self.token) # ключ и алгоритм прописан внутри
        except (ExpiredSignatureError, InvalidSignatureError, InvalidTokenError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный или истёкший access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

        if decoded_token.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ожидался access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return decoded_token

    @property
    def __get_user_statement(self) -> Select[tuple[UserModel]]:
        decoded_token: dict[str, Any] = self.__get_decoded_token()
        try:
            user_uuid = UUID(str(decoded_token["sub"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token не содержит корректного пользователя",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        return select(UserModel).where(UserModel.uuid == user_uuid)

    async def __set_user(
        self,
        auth_session: AsyncSession,
        redis_session: Redis,
    ) -> None:
        """
        Get user data, first - try to grab data from redis, else: go to db.
        Кеш: обновляем дату каждые 5 минут в кеше.
        """
        try:
            service_wrapper_logger.info("Set User")

            decoded_token: dict[str, Any] = self.__get_decoded_token()
            try:
                user_uuid = str(UUID(str(decoded_token["sub"])))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access token не содержит корректного пользователя",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from None

            service_wrapper_logger.info(f"Пользовательский uuid - {user_uuid}")

            cached_key = f"user:{user_uuid}"
            cached_user_data = await redis_session.get(cached_key)

            if cached_user_data:
                user_dict = json.loads(cached_user_data)
                self._user = UserModel(**user_dict)
                service_wrapper_logger.info("Вернули дату из кеша")

            else:
                self._user = (
                    await auth_session.execute(self.__get_user_statement)
                ).scalars().one()

                # manupulation with data for good work
                user_dict = json_helper.model_to_serializable_dict(self.user)

                await redis_session.setex(
                    cached_key, 
                    3, 
                    json.dumps(user_dict)
                )
                service_wrapper_logger.info("Вернули дату из бд и записали кеш")

        except NoResultFound:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

    async def __call__(self, *args, **kwargs) -> TResponse:
        # Authentication performs its own read-only unit of work. A SELECT
        # starts an implicit SQLAlchemy transaction, so it must not share the
        # session used by process(), where a service may open an explicit
        # atomic transaction with session.begin().
        async with async_session_manager.session() as auth_session:
            async with redis_session_manager.get_client() as redis_session:
                await self.__set_user(auth_session, redis_session)

                self.ensure_access()

        async with async_session_manager.session() as operation_session:
            self._session = operation_session
            async with redis_session_manager.get_client() as redis_session:
                self._redis_session = redis_session
                return await self.process(*args, **kwargs)


class BaseSuperuserAuthenticatedService[TResponse](
    BaseUserAuthenticatedService[TResponse],
    ABC,
):
    """Authenticated service restricted to active superusers."""

    def ensure_access(self) -> None:
        super().ensure_access()
        if not self.user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )


class AuthSessionService[TResponse](BaseSessionService[TResponse], ABC):
    serializer: URLSafeSerializer | None = None

    def __init__(self, /, **data: Any) -> None:
        super().__init__(**data)

        self.serializer = URLSafeSerializer(
            settings.email_settings.email_token_secret.get_secret_value()
        )