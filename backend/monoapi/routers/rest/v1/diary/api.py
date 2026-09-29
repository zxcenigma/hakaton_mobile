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
from monoapi.routers.services.diary.total_counts.get_week_counts import (
    GetWeekCountsService,
    RequestGetWeekCounts,
    ResponseGetWeekCounts,
)
from monoapi.routers.services.diary.total_counts.get_month_counts import (
    GetMonthCountsService,
    RequestGetMonthCounts,
    ResponseGetMonthCounts,
)
from monoapi.routers.services.diary.total_counts.get_year_counts import (
    GetYearCountsService,
    RequestGetYearCounts,
    ResponseGetYearCounts,
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
    return await GetDiaryWeekService(user_uuid=request.user_uuid, request_data=request)()


@router.get("/counts/week", response_model=ResponseGetWeekCounts)
async def counts_week(request: Annotated[RequestGetWeekCounts, Query()]) -> ResponseGetWeekCounts:
    return await GetWeekCountsService(user_uuid=request.user_uuid, request_data=request)()


@router.get("/counts/month", response_model=ResponseGetMonthCounts)
async def counts_month(request: Annotated[RequestGetMonthCounts, Query()]) -> ResponseGetMonthCounts:
    return await GetMonthCountsService(user_uuid=request.user_uuid, request_data=request)()


@router.get("/counts/year", response_model=ResponseGetYearCounts)
async def counts_year(request: Annotated[RequestGetYearCounts, Query()]) -> ResponseGetYearCounts:
    return await GetYearCountsService(user_uuid=request.user_uuid, request_data=request)()


@router.post("/operations", response_model=ResponseCreateDiaryOperation, status_code=201)
async def create_diary_operation(user_uuid: UUID, request: RequestCreateDiaryOperation) -> ResponseCreateDiaryOperation:
    return await CreateDiaryOperationService(user_uuid=user_uuid, request_data=request)()


@router.patch("/operations/{operation_uuid}", response_model=ResponseUpdateDiaryOperation, status_code=200)
async def update_diary_operation(user_uuid: UUID, request: RequestUpdateDiaryOperation, operation_uuid: UUID) -> ResponseUpdateDiaryOperation:
    return await UpdateDiaryOperationService(user_uuid=user_uuid, request_data=request, operation_uuid=operation_uuid)()


@router.delete("/operations/{operation_uuid}", status_code=204, response_class=Response)
async def delete_diary_operation(user_uuid: UUID, operation_uuid: UUID) -> Response:
    await DeleteDiaryOperationService(user_uuid=user_uuid, request_data=RequestDeleteDiaryOperation(operation_uuid=operation_uuid))()
    return Response(status_code=204)
