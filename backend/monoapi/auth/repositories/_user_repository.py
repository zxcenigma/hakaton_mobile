from uuid import UUID

from pydantic import EmailStr

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monoapi.db.models import UserModel

class UserRepository:
    
    async def get_user_by_email(self, async_session: AsyncSession,
                                email: EmailStr) -> UserModel | None:
        
        query = (select(UserModel)
                 .where(UserModel.email == email))
        stmt = await async_session.execute(query)
        return stmt.scalar_one_or_none()
    
    async def update_is_verified(self, async_session: AsyncSession,
                                 email: EmailStr) -> None:
        """
        CRUD используется для подтверждения аккаунта в бд
        """
        query = (update(UserModel)
                .where(UserModel.email == email)
                .values(is_verified=True))
        await async_session.execute(query)
        await async_session.commit()

    async def get_user_by_uuid(
        self,
        async_session: AsyncSession,
        user_uuid: str | UUID,
    ) -> UserModel | None:
        parsed_uuid = (
            user_uuid if isinstance(user_uuid, UUID) else UUID(str(user_uuid))
        )
        query = select(UserModel).where(UserModel.uuid == parsed_uuid)
        result = await async_session.execute(query)
        return result.scalar_one_or_none()


    async def get_current_user():
        pass




user_repo: UserRepository = UserRepository()
