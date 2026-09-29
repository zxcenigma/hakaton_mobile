from uuid import UUID
from datetime import date
from pydantic import Field, model_validator
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, get_user, totals


class RequestGetYearCounts(DiaryRequest):
    user_uuid: UUID
    date_from: date = Field(description="Начало диапазона включительно")
    date_to: date = Field(description="Конец диапазона, не включается")

    @model_validator(mode="after")
    def check_range(self):
        if self.date_from >= self.date_to:
            raise ValueError("date_from должна быть раньше date_to")
        return self


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
        return ResponseGetYearCounts(**await totals(
            self.async_session, user.id,
            self.request_data.date_from, self.request_data.date_to,
        ))
