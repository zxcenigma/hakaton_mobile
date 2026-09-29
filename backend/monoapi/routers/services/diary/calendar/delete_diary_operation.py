from uuid import UUID
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, get_user, get_operation
from monoapi.routers.services.targets.edit_target import apply_target_delta


class RequestDeleteDiaryOperation(DiaryRequest):
    operation_uuid: UUID


class DeleteDiaryOperationService(DiaryService[None]):
    request_data: RequestDeleteDiaryOperation

    async def process(self) -> None:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            operation = await get_operation(self.async_session, user.id, self.request_data.operation_uuid)
            await apply_target_delta(self.async_session, operation.target_id, -operation.amount)
            await self.async_session.delete(operation)
