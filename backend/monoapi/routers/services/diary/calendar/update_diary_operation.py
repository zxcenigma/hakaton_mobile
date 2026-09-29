from uuid import UUID
from fastapi import HTTPException
from pydantic import model_validator
from monoapi.db.enums import OperationType, OperationCategory
from monoapi.db.models import TargetModel
from monoapi.routers.services.diary._common import (
    DiaryRequest, DiaryService, Money, OperationName, CalendarDate,
    get_user, get_target, get_operation, validate_patch,
)
from monoapi.routers.services.targets.edit_target import apply_target_delta
from .create_diary_operation import ResponseCreateDiaryOperation, operation_response


class RequestUpdateDiaryOperation(DiaryRequest):
    name: OperationName | None = None
    operation_date: CalendarDate | None = None
    operation_type: OperationType | None = None
    amount: Money | None = None
    category: OperationCategory | None = None
    target_uuid: UUID | None = None

    @model_validator(mode="after")
    def check_patch(self):
        return validate_patch(self, {"name", "operation_date", "operation_type", "amount"})


class ResponseUpdateDiaryOperation(ResponseCreateDiaryOperation):
    pass


class UpdateDiaryOperationService(DiaryService[ResponseUpdateDiaryOperation]):
    operation_uuid: UUID
    request_data: RequestUpdateDiaryOperation

    async def process(self) -> ResponseUpdateDiaryOperation:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            operation = await get_operation(self.async_session, user.id, self.operation_uuid)
            old_target_id, old_amount = operation.target_id, operation.amount
            changes = self.request_data.model_dump(exclude_unset=True)
            new_type = changes.get("operation_type", operation.operation_type)
            if new_type != OperationType.INVESTMENT and changes.get("target_uuid") is not None:
                raise HTTPException(422, "Цель разрешена только для инвестиции")
            target = None
            if new_type == OperationType.INVESTMENT:
                if "target_uuid" in changes:
                    if changes["target_uuid"] is not None:
                        target = await get_target(self.async_session, user.id, changes["target_uuid"])
                elif old_target_id is not None:
                    target = await self.async_session.get(TargetModel, old_target_id)
            for name, value in changes.items():
                if name != "target_uuid":
                    setattr(operation, name, value)
            operation.target_id = target.id if target else None
            if old_target_id == operation.target_id:
                await apply_target_delta(self.async_session, old_target_id, operation.amount-old_amount)
            else:
                await apply_target_delta(self.async_session, old_target_id, -old_amount)
                await apply_target_delta(self.async_session, operation.target_id, operation.amount)
            await self.async_session.flush()
            await self.async_session.refresh(operation)
            response = ResponseUpdateDiaryOperation(**operation_response(operation, target.uuid if target else None))
        return response
