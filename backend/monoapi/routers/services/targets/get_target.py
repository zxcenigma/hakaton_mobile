from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import ConfigDict
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, get_user, get_target


class RequestGetTarget(DiaryRequest):
    target_uuid: UUID


class ResponseGetTarget(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    uuid: UUID
    name: str
    description: str | None
    current_count: int
    target_count: int
    percentage: Decimal
    created_at: datetime
    updated_at: datetime


class GetTargetService(DiaryService[ResponseGetTarget]):
    request_data: RequestGetTarget

    async def process(self) -> ResponseGetTarget:
        user = await get_user(self.async_session, self.user_uuid)
        target = await get_target(self.async_session, user.id, self.request_data.target_uuid)
        return ResponseGetTarget.model_validate(target)
