#!/usr/bin/env python3
"""Разовый перенос того, что уже накоплено в базе бэкенда, в платформу.

Запускается **на стороне бэкенда** — там, где есть доступ к PostgreSQL. Это
осознанно: в постоянном режиме бэкенд отдаёт события сам (схема outbox,
см. docs/integration-contract.md), и платформа в его базу не ходит. Прямое
чтение здесь — миграция, а не канал.

Из контейнера API:

    docker cp integration/backfill_from_backend.py hakaton_mobile_api:/tmp/
    docker cp ml_service/src/monetka/integration/backend_adapter.py \\
        hakaton_mobile_api:/tmp/
    docker exec -e PYTHONPATH=/monoapi:/tmp -e PG_HOST=hakaton_mobile_db \\
        -e ML_URL=http://host.docker.internal:8000 \\
        hakaton_mobile_api python /tmp/backfill_from_backend.py --username ник

Повторный запуск безопасен: `event_id` выводится из UUID записи, поэтому
платформа отбросит уже загруженное как дубликат.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

BATCH = 500


async def collect(username: str) -> list[dict]:
    from sqlalchemy import select

    from backend_adapter import diary_entry_to_event, target_to_events
    from monoapi.db import async_session_manager
    from monoapi.db.models import DiaryModel, TargetModel, UserModel

    async with async_session_manager.session() as session:
        user = (
            await session.execute(select(UserModel).where(UserModel.username == username))
        ).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"Пользователь {username!r} не найден")

        entries = list(
            (
                await session.execute(
                    select(DiaryModel)
                    .where(DiaryModel.user_id == user.id)
                    # Порядок обязателен: баланс считается накоплением, и при
                    # другом порядке строк он получится другим.
                    .order_by(DiaryModel.operation_date, DiaryModel.id)
                )
            ).scalars()
        )
        targets = list(
            (
                await session.execute(select(TargetModel).where(TargetModel.user_id == user.id))
            ).scalars()
        )

    if not entries:
        raise SystemExit("У пользователя нет операций — переносить нечего")

    first_day = entries[0].operation_date
    goal_by_id = {t.id: t for t in targets}

    events: list[dict] = []
    for target in targets:
        months = max(1, (entries[-1].operation_date.year - first_day.year) * 12
                     + (entries[-1].operation_date.month - first_day.month) + 1)
        events.extend(
            target_to_events(
                target_uuid=target.uuid,
                user_uuid=user.uuid,
                target_count=target.target_count,
                current_count=target.current_count,
                created_at=target.created_at,
                first_day=first_day,
                periods_taken=months,
            )
        )

    balance = 0
    savings = 0
    for entry in entries:
        before = balance
        if entry.operation_type == "income":
            balance += entry.amount
        else:
            balance -= entry.amount
        if entry.operation_type == "investment":
            savings += entry.amount

        target = goal_by_id.get(entry.target_id) if entry.target_id else None
        events.append(
            diary_entry_to_event(
                entry_uuid=entry.uuid,
                user_uuid=user.uuid,
                operation_type=str(entry.operation_type),
                name=entry.name,
                category=str(entry.category) if entry.category else None,
                amount=entry.amount,
                operation_date=entry.operation_date,
                occurred_at=entry.created_at,
                first_day=first_day,
                balance_before=before,
                balance_after=balance,
                goal_id=f"target:{target.uuid}" if target else None,
                savings_after=savings,
            )
        )
    return events


def post(url: str, events: list[dict]) -> dict:
    body = json.dumps({"source": "backend", "events": events}, ensure_ascii=False)
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/events:batch",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}", file=sys.stderr)
        raise SystemExit(2) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--ml-url", default=os.environ.get("ML_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, не отправлять")
    args = parser.parse_args()

    events = asyncio.run(collect(args.username))
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["event_name"]] = kinds.get(event["event_name"], 0) + 1
    print(f"Событий подготовлено: {len(events)} {kinds}")

    if args.dry_run:
        print(json.dumps(events[0], ensure_ascii=False, indent=2)[:600])
        return 0

    totals = {"received": 0, "accepted": 0, "duplicates": 0, "rejected": 0}
    for start in range(0, len(events), BATCH):
        result = post(args.ml_url, events[start : start + BATCH])
        for key in totals:
            totals[key] += result[key]
        for rejection in result.get("rejections", [])[:3]:
            print(f"  отвергнуто [{rejection['index']}]: {rejection['reason'][:160]}")
    print(f"Итог: {totals}")
    return 0 if totals["rejected"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
