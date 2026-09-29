from uuid import UUID
from datetime import date
from pydantic import Field
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, CalendarDate, get_user, totals, week_bounds


class RequestGetMonthCounts(DiaryRequest):
    user_uuid: UUID
    year: int = Field(ge=1, le=9998)
    month: int = Field(ge=1, le=12)


class ResponseGetMonthCounts(BaseModel):
    period_start: date
    period_end_exclusive: date
    income_total: int
    expense_total: int
    investment_total: int
    net_total: int


class GetMonthCountsService(DiaryService[ResponseGetMonthCounts]):
    request_data: RequestGetMonthCounts

    async def process(self) -> ResponseGetMonthCounts:
        user = await get_user(self.async_session, self.user_uuid)
        year, month = self.request_data.year, self.request_data.month
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return ResponseGetMonthCounts(**await totals(self.async_session, user.id, start, end))
