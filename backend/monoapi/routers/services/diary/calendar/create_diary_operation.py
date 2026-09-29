from datetime import date, datetime
from uuid import UUID
from pydantic import model_validator
from monoapi.db.enums import OperationType, OperationCategory
from monoapi.db.models import DiaryModel
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import (
    DiaryRequest, DiaryService, Money, OperationName, CalendarDate, get_user, get_target,
)
from monoapi.routers.services.targets.edit_target import apply_target_delta


class RequestCreateDiaryOperation(DiaryRequest):
    name: OperationName
    operation_date: CalendarDate
    operation_type: OperationType
    amount: Money
    category: OperationCategory | None = None
    target_uuid: UUID | None = None

    @model_validator(mode="after")
    def check_target(self):
        if self.target_uuid is not None and self.operation_type != OperationType.INVESTMENT:
            raise ValueError("Цель разрешена только для инвестиции")
        return self


class ResponseCreateDiaryOperation(BaseModel):
    uuid: UUID
    name: str
    operation_date: date
    operation_type: OperationType
    amount: int
    category: OperationCategory | None
    target_uuid: UUID | None
    created_at: datetime
    updated_at: datetime


def operation_response(operation: DiaryModel, target_uuid: UUID | None) -> dict:
    return dict(uuid=operation.uuid, name=operation.name, operation_date=operation.operation_date,
                operation_type=operation.operation_type, amount=operation.amount,
                category=operation.category, target_uuid=target_uuid,
                created_at=operation.created_at, updated_at=operation.updated_at)


class CreateDiaryOperationService(DiaryService[ResponseCreateDiaryOperation]):
    request_data: RequestCreateDiaryOperation

    async def process(self) -> ResponseCreateDiaryOperation:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            target = None
            if self.request_data.target_uuid is not None:
                target = await get_target(self.async_session, user.id, self.request_data.target_uuid)
            operation = DiaryModel(user_id=user.id, target_id=target.id if target else None,
                                   **self.request_data.model_dump(exclude={"target_uuid"}))
            self.async_session.add(operation)
            await apply_target_delta(self.async_session, operation.target_id, operation.amount)
            await self.async_session.flush()
            response = ResponseCreateDiaryOperation(**operation_response(operation, target.uuid if target else None))
        return response
