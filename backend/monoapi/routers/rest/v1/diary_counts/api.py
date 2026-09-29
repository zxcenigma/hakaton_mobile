from typing import Annotated

from fastapi import APIRouter, Query

from monoapi.helpers.pydantic import BaseModel
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


class CountsErrorResponse(BaseModel):
    detail: str | list[dict]


router = APIRouter(
    prefix="/diary_counts",
    tags=["diary_counts"],
    responses={
        404: {"model": CountsErrorResponse, "description": "Пользователь не найден"},
        422: {"model": CountsErrorResponse, "description": "Некорректный диапазон дат"},
    },
)


@router.get(
    "/week", 
    response_model=ResponseGetWeekCounts
)
async def counts_week(
    request: Annotated[RequestGetWeekCounts, Query()]) -> ResponseGetWeekCounts:
    service = GetWeekCountsService(
        user_uuid=request.user_uuid, 
        request_data=request
    )
    return await service()


@router.get(
    "/month", 
    response_model=ResponseGetMonthCounts
)
async def counts_month(
    request: Annotated[RequestGetMonthCounts, Query()]) -> ResponseGetMonthCounts:
    service = GetMonthCountsService(
        user_uuid=request.user_uuid, 
        request_data=request
    )
    return await service()


@router.get(
    "/year", 
    response_model=ResponseGetYearCounts
)
async def counts_year(
    request: Annotated[RequestGetYearCounts, Query()]) -> ResponseGetYearCounts:
    service = GetYearCountsService(
        user_uuid=request.user_uuid, 
        request_data=request
    )
    return await service()
