#!/usr/bin/env python3
"""Заполнить дневник существующего пользователя за последние 90 дней.

Из корня проекта:
    backend/.venv/bin/python .temp/seed_user_activity.py --dry-run
    backend/.venv/bin/python .temp/seed_user_activity.py
    backend/.venv/bin/python .temp/seed_user_activity.py --username другой_ник

Подключение берётся из backend/.env; переменные PG_* могут переопределить его.
Повторный запуск для того же пользователя не добавляет дубли.


PG_HOST=127.0.0.1 PG_PORT=5432 \
backend/.venv/bin/python .temp/seed_user_activity.py --username
"""
import argparse
import asyncio
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
import random
import sys
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from monoapi.db import async_session_manager
from monoapi.db.enums import OperationCategory, OperationType
from monoapi.db.models import DiaryModel, TargetModel, UserModel

DAYS = 90
TARGET_AMOUNT = 12_900
SAVED_AMOUNT = 8_643
TARGET_NAME = "Наушники с шумоподавлением"
SEED_KEY = "seed-user-activity-90-days-v1"
TIMEZONE = ZoneInfo("Europe/Moscow")


def target_uuid(user_uuid: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"{SEED_KEY}:{user_uuid}:target")


def build_operations(user: UserModel, target: TargetModel, end_date: date) -> list[DiaryModel]:
    rng = random.Random(67)
    start = end_date - timedelta(days=DAYS - 1)
    # Разные ежедневные взносы, в сумме строго 8 643 рубля.
    weights = [rng.randint(1, 10) for _ in range(DAYS)]
    available = SAVED_AMOUNT - 50 * DAYS
    investments = [50 + available * weight // sum(weights) for weight in weights]
    for index in range(SAVED_AMOUNT - sum(investments)):
        investments[index] += 1

    expenses = [
        ("Продукты на ужин", OperationCategory.SUPERMARKETS, 250, 1500),
        ("Кофе с собой", OperationCategory.COFFEE_SHOPS, 150, 350),
        ("Проезд", OperationCategory.PUBLIC_TRANSPORT, 60, 180),
        ("Обед", OperationCategory.FAST_FOOD, 250, 600),
        ("Поход в кино", OperationCategory.CINEMA, 350, 900),
        ("Книга", OperationCategory.BOOKS, 300, 1200),
        ("Заказ ужина", OperationCategory.FOOD_DELIVERY, 500, 1800),
    ]
    rows = []

    def add(day, hour, name, kind, amount, category=None):
        timestamp = datetime.combine(day, time(hour), tzinfo=TIMEZONE)
        rows.append(DiaryModel(
            uuid=uuid5(NAMESPACE_URL, f"{SEED_KEY}:{user.uuid}:operation:{len(rows)}"),
            user_id=user.id,
            target_id=target.id if kind == OperationType.INVESTMENT else None,
            name=name, operation_date=day, operation_type=kind,
            amount=amount, category=category,
            created_at=timestamp, updated_at=timestamp,
        ))

    for index in range(DAYS):
        day = start + timedelta(days=index)
        if index % 15 == 0:
            add(day, 8, "Зарплата" if index % 30 == 0 else "Аванс", OperationType.INCOME, 20_000)
        if index % 21 == 10:
            add(day, 9, "Подработка", OperationType.INCOME, rng.randint(2000, 6000))
        name, category, minimum, maximum = rng.choice(expenses)
        add(day, 12, name, OperationType.EXPENSE, rng.randint(minimum, maximum), category)
        if index % 3 == 0:
            add(day, 16, "Продукты домой", OperationType.EXPENSE,
                rng.randint(300, 1000), OperationCategory.SUPERMARKETS)
        add(day, 18, "Пополнение: наушники", OperationType.INVESTMENT, investments[index])
    return rows


async def seed(username: str, end_date: date, dry_run: bool) -> None:
    try:
        async with async_session_manager.session() as session:
            async with session.begin():
                # Тот же порядок блокировки, что у сервисов дневника/целей.
                users = (await session.scalars(select(UserModel).where(
                    UserModel.username == username,
                ).with_for_update())).all()
                if not users:
                    raise ValueError(f"Пользователь {username!r} не найден. Сначала создайте его в приложении.")
                if len(users) != 1:
                    raise ValueError(f"Найдено несколько пользователей с ником {username!r}; нужен уникальный ник.")
                user = users[0]
                identifier = target_uuid(user.uuid)
                existing = await session.scalar(select(TargetModel).where(TargetModel.uuid == identifier))
                if existing is not None:
                    print(f"Тестовые данные уже созданы: цель {existing.uuid}. Повторная запись пропущена.")
                    return
                start = end_date - timedelta(days=DAYS - 1)
                target = TargetModel(
                    uuid=identifier, user_id=user.id, name=TARGET_NAME,
                    description="Тестовая цель: накопить на беспроводные наушники. История за 90 дней.",
                    target_count=TARGET_AMOUNT, current_count=SAVED_AMOUNT,
                    percentage=(Decimal(SAVED_AMOUNT) / Decimal(TARGET_AMOUNT) * 100).quantize(Decimal("0.01")),
                    created_at=datetime.combine(start, time(7), tzinfo=TIMEZONE),
                    updated_at=datetime.combine(end_date, time(18), tzinfo=TIMEZONE),
                )
                if not dry_run:
                    session.add(target)
                    await session.flush()
                rows = build_operations(user, target, end_date)
                assert sum(row.amount for row in rows if row.operation_type == OperationType.INVESTMENT) == SAVED_AMOUNT
                if not dry_run:
                    session.add_all(rows)
                    await session.flush()
                counts = Counter(row.operation_type.value for row in rows)
                report = (f"Пользователь: {username}; период: {start} — {end_date}\n"
                          f"Операций: {len(rows)} ({dict(counts)})\n"
                          f"Цель: {TARGET_NAME}; UUID: {identifier}\n"
                          f"Накоплено: {SAVED_AMOUNT} / {TARGET_AMOUNT} ₽ ({target.percentage}%)")
            print(("Проверка без записи.\n" if dry_run else "Данные записаны.\n") + report)
    finally:
        await async_session_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", default="username")
    parser.add_argument("--end-date", type=date.fromisoformat, default=datetime.now(TIMEZONE).date(),
                        help="Последний день периода включительно, YYYY-MM-DD (по умолчанию сегодня по Москве)")
    parser.add_argument("--dry-run", action="store_true", help="Проверить и показать план без записи в БД")
    args = parser.parse_args()
    try:
        asyncio.run(seed(args.username, args.end_date, args.dry_run))
    except (ValueError, IntegrityError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Конфликт данных. Транзакция отменена; возможно, ранее созданные операции уже существуют."
        parser.exit(1, message + "\n")


if __name__ == "__main__":
    main()
