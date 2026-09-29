from monoapi.db.models import TargetModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, Money, TargetName, get_user
from .get_target import ResponseGetTarget


class RequestCreateTarget(DiaryRequest):
    name: TargetName
    description: str | None = None
    target_count: Money


class ResponseCreateTarget(ResponseGetTarget):
    pass


class CreateTargetService(DiaryService[ResponseCreateTarget]):
    request_data: RequestCreateTarget

    async def process(self) -> ResponseCreateTarget:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            target = TargetModel(user_id=user.id, **self.request_data.model_dump())
            self.async_session.add(target)
            await self.async_session.flush()
            response = ResponseCreateTarget.model_validate(target)
        return response
