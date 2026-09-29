from uuid import UUID
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, get_user, get_target


class RequestDeleteTarget(DiaryRequest):
    target_uuid: UUID


class DeleteTargetService(DiaryService[None]):
    request_data: RequestDeleteTarget

    async def process(self) -> None:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            target = await get_target(self.async_session, user.id, self.request_data.target_uuid)
            # FK ON DELETE SET NULL preserves the diary and all financial totals.
            await self.async_session.delete(target)
