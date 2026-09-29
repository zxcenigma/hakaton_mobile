import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monoapi.auth.schemas import TokenInfoSchema
from monoapi.auth.utils import encode_jwt
from monoapi.core import settings
from monoapi.db.models import UserModel, UserSessionModel


def hash_refresh_token(token: str) -> str:
    """Return a non-reversible database representation of a refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenRepository:
    def create_access_token(self, user: UserModel) -> str:
        return encode_jwt(
            payload={
                **self._user_payload(user),
                "type": "access",
            },
            expire_timedelta=timedelta(
                minutes=float(settings.auth_jwt.jwt_access_minutes)
            ),
        )

    async def create_tokens(
        self,
        user: UserModel,
        async_session: AsyncSession,
        presented_refresh_token: str | None = None,
    ) -> tuple[TokenInfoSchema, str]:
        """Issue access and refresh tokens while keeping one session per user."""
        session = await self.get_by_user_id(user.id, async_session)
        if (
            session is not None
            and presented_refresh_token
            and not session.revoked
            and not self.is_expired_refresh(session)
            and session.token == hash_refresh_token(presented_refresh_token)
        ):
            return (
                TokenInfoSchema(access_token=self.create_access_token(user)),
                presented_refresh_token,
            )

        refresh_token = encode_jwt(
            payload={
                **self._user_payload(user),
                "type": "refresh",
                "jti": str(uuid4()),
            }
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=float(settings.auth_jwt.jwt_available_days)
        )
        if session is None:
            session = UserSessionModel(user_id=user.id)
            async_session.add(session)

        session.token = hash_refresh_token(refresh_token)
        session.expires_at = expires_at
        session.revoked = False
        await async_session.commit()

        return (
            TokenInfoSchema(access_token=self.create_access_token(user)),
            refresh_token,
        )

    async def get_by_user_id(
        self,
        user_id: int,
        async_session: AsyncSession,
    ) -> UserSessionModel | None:
        result = await async_session.execute(
            select(UserSessionModel).where(UserSessionModel.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_refresh(
        self,
        token: str,
        async_session: AsyncSession,
    ) -> UserSessionModel | None:
        result = await async_session.execute(
            select(UserSessionModel).where(
                UserSessionModel.token == hash_refresh_token(token)
            )
        )
        return result.scalar_one_or_none()

    async def revoke_refresh(
        self,
        token: str,
        async_session: AsyncSession,
    ) -> None:
        session = await self.get_refresh(token, async_session)
        if session is not None:
            session.revoked = True
            await async_session.commit()

    @staticmethod
    def is_expired_refresh(session: UserSessionModel) -> bool:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @staticmethod
    def _user_payload(user: UserModel) -> dict[str, str]:
        return {
            "sub": str(user.uuid),
            "username": user.username,
        }


token_repo = TokenRepository()
