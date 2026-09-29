from uuid import UUID
from datetime import date, timedelta
from sqlalchemy import select
from monoapi.db.enums import OperationType
from monoapi.db.models import DiaryModel, TargetModel
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.diary._common import DiaryRequest, DiaryService, CalendarDate, get_user, week_bounds
from .create_diary_operation import ResponseCreateDiaryOperation, operation_response


class RequestGetDiaryWeek(DiaryRequest):
    user_uuid: UUID
    anchor_date: CalendarDate


class DiaryDay(BaseModel):
    date: date
    operations: list[ResponseCreateDiaryOperation]
    income_total: int = 0
    expense_total: int = 0
    investment_total: int = 0
    net_total: int = 0


class ResponseGetDiaryWeek(BaseModel):
    anchor_date: date
    week_start: date
    week_end: date
    display_month: int
    display_year: int
    days: list[DiaryDay]


class GetDiaryWeekService(DiaryService[ResponseGetDiaryWeek]):
    request_data: RequestGetDiaryWeek

    async def process(self) -> ResponseGetDiaryWeek:
        user = await get_user(self.async_session, self.user_uuid)
        anchor = self.request_data.anchor_date
        start, end = week_bounds(anchor)
        rows = (await self.async_session.execute(
            select(DiaryModel, TargetModel.uuid).outerjoin(TargetModel, DiaryModel.target_id == TargetModel.id)
            .where(DiaryModel.user_id == user.id, DiaryModel.operation_date >= start,
                   DiaryModel.operation_date < end)
            .order_by(DiaryModel.created_at, DiaryModel.id)
        )).all()
        days = {start + timedelta(days=i): DiaryDay(date=start + timedelta(days=i), operations=[]) for i in range(7)}
        for operation, target_uuid in rows:
            day = days[operation.operation_date]
            day.operations.append(ResponseCreateDiaryOperation(**operation_response(operation, target_uuid)))
            field = {OperationType.INCOME: "income_total", OperationType.EXPENSE: "expense_total",
                     OperationType.INVESTMENT: "investment_total"}[operation.operation_type]
            setattr(day, field, getattr(day, field) + operation.amount)
            day.net_total = day.income_total-day.expense_total-day.investment_total
        return ResponseGetDiaryWeek(anchor_date=anchor, week_start=start, week_end=end-timedelta(days=1),
                                    display_month=anchor.month, display_year=anchor.year, days=list(days.values()))
