from fastapi import HTTPException, status
from jwt import ExpiredSignatureError, InvalidTokenError

from monoapi.auth.repositories import token_repo, user_repo
from monoapi.auth.schemas import (
    ResponseSignUp,
    SignInSchema,
    SignUpSchema,
    TokenInfoSchema,
)
from monoapi.auth.utils import decode_jwt
from monoapi.db.models import UserModel
from monoapi.routers.services._base import AuthSessionService


class SignUpService(AuthSessionService[ResponseSignUp]):
    request_data: SignUpSchema

    async def process(self) -> ResponseSignUp:
        user = UserModel(
            username=self.request_data.username,
            age=self.request_data.age
        )
        self.async_session.add(user)
        await self.async_session.commit()

        return ResponseSignUp()


class SignInService(AuthSessionService[tuple[TokenInfoSchema, str]]):
    request_data: SignInSchema
    current_refresh_token: str | None = None

    async def process(self) -> tuple[TokenInfoSchema, str]:
        user = await user_repo.get_user_by_username(
            self.async_session,
            self.request_data.username,
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь деактивирован",
            )
        return await token_repo.create_tokens(
            user,
            self.async_session,
            self.current_refresh_token,
        )


class RefreshService(AuthSessionService[TokenInfoSchema]):
    refresh_token: str

    async def process(self) -> TokenInfoSchema:
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Войдите снова",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = decode_jwt(self.refresh_token)
        except (ExpiredSignatureError, InvalidTokenError):
            raise unauthorized from None

        if payload.get("type") != "refresh" or not payload.get("sub"):
            raise unauthorized

        session = await token_repo.get_refresh(
            self.refresh_token,
            self.async_session,
        )
        if (
            session is None
            or session.revoked
            or token_repo.is_expired_refresh(session)
        ):
            raise unauthorized

        user = await user_repo.get_user_by_uuid(
            self.async_session,
            payload["sub"],
        )
        if (
            user is None
            or user.id != session.user_id
            or not user.is_active
        ):
            raise unauthorized

        return TokenInfoSchema(
            access_token=token_repo.create_access_token(user)
        )


class LogoutService(AuthSessionService[None]):
    refresh_token: str | None = None

    async def process(self) -> None:
        if self.refresh_token:
            await token_repo.revoke_refresh(
                self.refresh_token,
                self.async_session,
            )
