from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Query, Response
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary.calendar.get_diary_week import (
    GetDiaryWeekService,
    RequestGetDiaryWeek,
    ResponseGetDiaryWeek,
)
from monoapi.routers.services.diary.calendar.create_diary_operation import (
    CreateDiaryOperationService,
    RequestCreateDiaryOperation,
    ResponseCreateDiaryOperation,
)
from monoapi.routers.services.diary.calendar.update_diary_operation import (
    UpdateDiaryOperationService,
    RequestUpdateDiaryOperation,
    ResponseUpdateDiaryOperation,
)
from monoapi.routers.services.diary.calendar.delete_diary_operation import (
    DeleteDiaryOperationService,
    RequestDeleteDiaryOperation,
)


class DiaryErrorResponse(BaseModel):
    detail: str | list[dict]


router = APIRouter(prefix="/diary", tags=["diary"], responses={
    404: {"model": DiaryErrorResponse, "description": "Пользователь, операция или цель не найдены"},
    422: {"model": DiaryErrorResponse, "description": "Ошибка валидации параметров или состояния операции"},
    409: {"model": DiaryErrorResponse, "description": "Конфликт состояния накоплений"},
})

@router.get("/week", response_model=ResponseGetDiaryWeek)
async def week(request: Annotated[RequestGetDiaryWeek, Query()]) -> ResponseGetDiaryWeek:
    service = GetDiaryWeekService(user_uuid=request.user_uuid, request_data=request)
    return await service()


@router.post("/operations", response_model=ResponseCreateDiaryOperation, status_code=201)
async def create_diary_operation(user_uuid: UUID, request: RequestCreateDiaryOperation) -> ResponseCreateDiaryOperation:
    service = CreateDiaryOperationService(user_uuid=user_uuid, request_data=request)
    return await service()


@router.patch("/operations/{operation_uuid}", response_model=ResponseUpdateDiaryOperation, status_code=200)
async def update_diary_operation(user_uuid: UUID, request: RequestUpdateDiaryOperation, operation_uuid: UUID) -> ResponseUpdateDiaryOperation:
    service = UpdateDiaryOperationService(user_uuid=user_uuid, request_data=request, operation_uuid=operation_uuid)
    return await service()


@router.delete("/operations/{operation_uuid}", status_code=204, response_class=Response)
async def delete_diary_operation(user_uuid: UUID, operation_uuid: UUID) -> Response:
    service = DeleteDiaryOperationService(user_uuid=user_uuid, request_data=RequestDeleteDiaryOperation(operation_uuid=operation_uuid))
    await service()
    return Response(status_code=204)
