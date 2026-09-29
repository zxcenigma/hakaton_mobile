from datetime import date, timedelta
from typing import Annotated, ClassVar
from uuid import UUID

from fastapi import HTTPException
from pydantic import ConfigDict, Field, StringConstraints
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monoapi.db.models import DiaryModel, TargetModel, UserModel
from monoapi.db.enums import OperationType
from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services._base import BaseSessionService

Money = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
OperationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TargetName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CalendarDate = Annotated[date, Field(le=date(9998, 12, 31))]


class DiaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiaryService[T](BaseSessionService[T]):
    use_redis: ClassVar[bool] = False
    user_uuid: UUID


async def get_user(session: AsyncSession, user_uuid: UUID, *, lock: bool = False) -> UserModel:
    statement = select(UserModel).where(UserModel.uuid == user_uuid)
    # Every diary/target writer takes this lock FIRST, before reading operations.
    # Serializing writes per user avoids stale totals and target/operation deadlocks.
    if lock:
        statement = statement.with_for_update()
    user = await session.scalar(statement)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


async def get_target(session: AsyncSession, user_id: int, target_uuid: UUID) -> TargetModel:
    target = await session.scalar(select(TargetModel).where(
        TargetModel.user_id == user_id, TargetModel.uuid == target_uuid,
    ))
    if target is None:
        raise HTTPException(404, "Цель не найдена")
    return target


async def get_operation(session: AsyncSession, user_id: int, operation_uuid: UUID) -> DiaryModel:
    operation = await session.scalar(select(DiaryModel).where(
        DiaryModel.user_id == user_id, DiaryModel.uuid == operation_uuid,
    ))
    if operation is None:
        raise HTTPException(404, "Операция не найдена")
    return operation


def validate_patch(request: BaseModel, required: set[str]):
    if not request.model_fields_set:
        raise ValueError("Укажите хотя бы одно поле для изменения")
    if any(getattr(request, name) is None for name in request.model_fields_set & required):
        raise ValueError("Обязательные поля не могут быть null")
    return request


def week_bounds(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=7)


async def totals(session: AsyncSession, user_id: int, start: date, end: date) -> dict:
    row = (await session.execute(select(*[
        func.coalesce(func.sum(case((DiaryModel.operation_type == kind, DiaryModel.amount), else_=0)), 0)
        for kind in (OperationType.INCOME, OperationType.EXPENSE, OperationType.INVESTMENT)
    ]).where(DiaryModel.user_id == user_id, DiaryModel.operation_date >= start,
             DiaryModel.operation_date < end))).one()
    income, expense, investment = map(int, row)
    return dict(period_start=start, period_end_exclusive=end, income_total=income,
                expense_total=expense, investment_total=investment,
                net_total=income-expense-investment)
