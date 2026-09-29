from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from monoapi.db.models import TargetModel
from monoapi.routers.services.diary._common import (
    DiaryRequest, DiaryService, Money, TargetName, get_user, get_target, validate_patch,
)
from .get_target import ResponseGetTarget


def update_percentage(target: TargetModel) -> None:
    target.percentage = min(Decimal(target.current_count) / Decimal(target.target_count) * 100,
                            Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def apply_target_delta(session: AsyncSession, target_id: int | None, delta: int) -> None:
    """Caller holds the user's row lock and owns the transaction; no commit here.

    Deltas preserve any pre-existing opening savings without inventing diary income.
    For goals created by this API the initial savings are zero.
    """
    if target_id is None or delta == 0:
        return
    target = await session.get(TargetModel, target_id)
    if target is None:
        raise HTTPException(409, "Цель была удалена")
    new_count = target.current_count + delta
    if not 0 <= new_count <= 9223372036854775807:
        raise HTTPException(409, "Накопление цели выходит за допустимый диапазон")
    target.current_count = new_count
    update_percentage(target)


class RequestEditTarget(DiaryRequest):
    name: TargetName | None = None
    description: str | None = None
    target_count: Money | None = None

    @model_validator(mode="after")
    def check_patch(self):
        return validate_patch(self, {"name", "target_count"})


class ResponseEditTarget(ResponseGetTarget):
    pass


class EditTargetService(DiaryService[ResponseEditTarget]):
    target_uuid: UUID
    request_data: RequestEditTarget

    async def process(self) -> ResponseEditTarget:
        async with self.async_session.begin():
            user = await get_user(self.async_session, self.user_uuid, lock=True)
            target = await get_target(self.async_session, user.id, self.target_uuid)
            for name, value in self.request_data.model_dump(exclude_unset=True).items():
                setattr(target, name, value)
            update_percentage(target)
            await self.async_session.flush()
            await self.async_session.refresh(target)
            response = ResponseEditTarget.model_validate(target)
        return response
