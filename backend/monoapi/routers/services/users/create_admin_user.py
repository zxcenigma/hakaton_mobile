from fastapi import HTTPException, status
from pydantic import EmailStr, Field, SecretStr, UUID4

from monoapi.auth.repositories import user_repo
from monoapi.auth.utils import hash_password
from monoapi.db.models import UserModel
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services import BaseSuperuserAuthenticatedService

USER_MANAGER_EMAILS = {"user@example.ru"}


class CreateAdminUserRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=4, max_length=24)
    password: SecretStr = Field(min_length=8, max_length=64)


class CreateAdminUserResponse(BaseModel):
    uuid: UUID4
    email: EmailStr
    username: str
    is_active: bool
    is_verified: bool
    is_superuser: bool


class CreateAdminUserService(
    BaseSuperuserAuthenticatedService[CreateAdminUserResponse]
):
    request_data: CreateAdminUserRequest

    def ensure_access(self) -> None:
        super().ensure_access()
        if str(self.user.email).casefold() not in USER_MANAGER_EMAILS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="У пользователя нет права создавать учётные записи",
            )

    async def process(self, *args, **kwargs) -> CreateAdminUserResponse:
        existing = await user_repo.get_user_by_email(
            self.async_session,
            self.request_data.email,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с такой почтой уже существует",
            )

        user = UserModel(
            email=self.request_data.email,
            username=self.request_data.username,
            password=hash_password(
                self.request_data.password.get_secret_value()
            ),
            is_active=True,
            is_verified=True,
            is_superuser=True,
        )
        self.async_session.add(user)
        await self.async_session.commit()
        await self.async_session.refresh(user)

        return CreateAdminUserResponse(
            uuid=user.uuid,
            email=user.email,
            username=user.username,
            is_active=user.is_active,
            is_verified=user.is_verified,
            is_superuser=user.is_superuser,
        )
