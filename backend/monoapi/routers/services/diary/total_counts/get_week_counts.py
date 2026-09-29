from uuid import UUID
from datetime import date
from pydantic import Field
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, CalendarDate, get_user, totals, week_bounds


class RequestGetWeekCounts(DiaryRequest):
    user_uuid: UUID
    anchor_date: CalendarDate


class ResponseGetWeekCounts(BaseModel):
    period_start: date
    period_end_exclusive: date
    income_total: int
    expense_total: int
    investment_total: int
    net_total: int


class GetWeekCountsService(DiaryService[ResponseGetWeekCounts]):
    request_data: RequestGetWeekCounts

    async def process(self) -> ResponseGetWeekCounts:
        user = await get_user(self.async_session, self.user_uuid)
        start, end = week_bounds(self.request_data.anchor_date)
        return ResponseGetWeekCounts(**await totals(self.async_session, user.id, start, end))
