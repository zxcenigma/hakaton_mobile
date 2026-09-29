from uuid import UUID
from datetime import date
from pydantic import Field
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, CalendarDate, get_user, totals, week_bounds


class RequestGetYearCounts(DiaryRequest):
    user_uuid: UUID
    year: int = Field(ge=1, le=9998)


class ResponseGetYearCounts(BaseModel):
    period_start: date
    period_end_exclusive: date
    income_total: int
    expense_total: int
    investment_total: int
    net_total: int


class GetYearCountsService(DiaryService[ResponseGetYearCounts]):
    request_data: RequestGetYearCounts

    async def process(self) -> ResponseGetYearCounts:
        user = await get_user(self.async_session, self.user_uuid)
        start = date(self.request_data.year, 1, 1)
        end = date(self.request_data.year + 1, 1, 1)
        return ResponseGetYearCounts(**await totals(self.async_session, user.id, start, end))
