"""Отображение моделей бэкенда в события платформы.

Эталонная реализация контракта из
[`docs/integration-contract.md`](../../../docs/integration-contract.md).
Функции здесь чистые и без зависимостей от бэкенда — их можно скопировать в
Celery-задачу, которая пишет outbox, и ничего не потянется следом.

Что здесь решается и почему это важно:

* **Псевдонимизация.** Бэкенд знает пользователя, платформа — нет и знать не
  должна. `profile_pseudo_id` — односторонняя функция от UUID пользователя:
  стабильная, чтобы можно было считать историю профиля, и необратимая, чтобы
  ТЗ §3.5 выполнялся свойством системы, а не обещанием не делать `SELECT email`.
* **Нужное против желаемого.** Это ядро ТЗ (§2.5.3) и единственное место, где
  техническое отображение упирается в методику. Таблица ниже — предложение, а
  не истина; её должен просмотреть методист, и она вынесена отдельно именно
  чтобы её было где просмотреть.
* **Контекст устройства.** Его у ретранслированного события нет, и мы его не
  выдумываем: `app_version` и `android_api_level` остаются пустыми.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from monetka.common.events import ExpenseCategory, IncomeSource

#: Пространство имён для псевдонимизации. Меняется — меняются все
#: идентификаторы, поэтому меняться не должно.
PROFILE_NAMESPACE = uuid.UUID("6f0c9f4e-0a3a-4c1e-9f2a-7d5b1c8e4a20")
SESSION_NAMESPACE = uuid.UUID("2b7d3a51-9c64-4f8e-bb02-1a6f5d9c3e77")

#: Как категории дневника делятся на обязательное и желаемое.
#:
#: Это **методическое** решение, а не техническое: от него зависит, что
#: приложение скажет ребёнку про его выбор. Границы спорные по построению —
#: «Спорт и фитнес» для одной семьи обязательное, для другой нет, — поэтому
#: таблица лежит в одном месте, читается за минуту и меняется одной строкой.
#:
#: Всё, чего здесь нет, считается желаемым: ошибиться в сторону «желаемого»
#: безопаснее. Подсказка тогда предложит подумать над тратой, а не промолчит
#: о том, что ребёнок не закрыл необходимое.
ESSENTIAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "Супермаркеты",
        "Общественный транспорт",
        "Здоровье и медицина",
        "Аптеки",
        "Образование",
        "Детские товары",
        "Одежда и обувь",
    }
)

#: Как названия доходов отображаются в источник.
#:
#: Соответствие приблизительное и это честнее отметить: перечисление платформы
#: описывает игровую экономику ребёнка (начисление за период, награда за
#: задание, бонус от взрослого), а дневник — взрослые доходы. Пока продукт не
#: определился с аудиторией, регулярный доход считается начислением за период,
#: нерегулярный — бонусом.
REGULAR_INCOME_MARKERS = ("зарплат", "аванс", "стипенди", "карманн", "пособи")


def profile_pseudo_id(user_uuid: uuid.UUID | str) -> uuid.UUID:
    """Псевдоним профиля. Стабильный, необратимый, без персональных данных."""
    return uuid.uuid5(PROFILE_NAMESPACE, str(user_uuid))


def session_id_for(profile: uuid.UUID, day: date) -> uuid.UUID:
    """Идентификатор сессии для ретранслированного события.

    У записи дневника нет сессии: пользователь не «открывал приложение», он
    добавил операцию. Сессия на день — не выдумка про поведение, а способ
    сгруппировать события одного дня так, чтобы витрины работали одинаково
    для обоих источников. Детерминированно, поэтому повторный бэкфилл даёт те
    же идентификаторы.
    """
    return uuid.uuid5(SESSION_NAMESPACE, f"{profile}:{day.isoformat()}")


def period_no_for(first_day: date, day: date) -> int:
    """Порядковый номер периода.

    Период платформы — это игровой цикл «получил доход → распланировал →
    потратил → подвёл итог» (ТЗ §2.5.5). В дневнике ему соответствует
    календарный месяц: доход приходит раз в месяц, и итог подводится по нему.
    Отсчёт от первой операции пользователя, а не от календаря, — иначе у
    начавшего в декабре первый период окажется обрезанным.
    """
    return (day.year - first_day.year) * 12 + (day.month - first_day.month) + 1


def expense_category_for(diary_category: str | None) -> ExpenseCategory:
    """Обязательная трата или желаемая. См. `ESSENTIAL_CATEGORIES`."""
    if diary_category and diary_category in ESSENTIAL_CATEGORIES:
        return ExpenseCategory.ESSENTIAL
    return ExpenseCategory.OPTIONAL


def income_source_for(operation_name: str) -> IncomeSource:
    """Регулярный доход или разовый. См. `REGULAR_INCOME_MARKERS`."""
    lowered = (operation_name or "").lower()
    if any(marker in lowered for marker in REGULAR_INCOME_MARKERS):
        return IncomeSource.PERIOD_ALLOWANCE
    return IncomeSource.ADULT_BONUS


def _envelope(
    *,
    event_name: str,
    profile: uuid.UUID,
    occurred_at: datetime,
    day: date,
    first_day: date,
    payload: dict[str, Any],
    event_uuid: uuid.UUID,
) -> dict[str, Any]:
    """Конверт без контекста устройства — его у ретранслятора нет."""
    return {
        "event_id": str(event_uuid),
        "event_name": event_name,
        "schema_version": 1,
        "occurred_at": occurred_at.isoformat(),
        "profile_pseudo_id": str(profile),
        "session_id": str(session_id_for(profile, day)),
        "period_no": period_no_for(first_day, day),
        "demo_mode": False,
        "payload": payload,
    }


def diary_entry_to_event(
    *,
    entry_uuid: uuid.UUID,
    user_uuid: uuid.UUID,
    operation_type: str,
    name: str,
    category: str | None,
    amount: int,
    operation_date: date,
    occurred_at: datetime,
    first_day: date,
    balance_before: int,
    balance_after: int,
    goal_id: str | None = None,
    savings_after: int = 0,
) -> dict[str, Any]:
    """Одна запись дневника → одно событие платформы.

    `event_id` выводится из UUID записи, а не генерируется: повторный бэкфилл
    и повтор доставки дают тот же идентификатор, и платформа отбрасывает
    дубликат вместо того, чтобы удвоить историю.
    """
    profile = profile_pseudo_id(user_uuid)
    event_uuid = uuid.uuid5(PROFILE_NAMESPACE, f"diary:{entry_uuid}")

    def envelope(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return _envelope(
            event_name=event_name,
            profile=profile,
            occurred_at=occurred_at,
            day=operation_date,
            first_day=first_day,
            payload=payload,
            event_uuid=event_uuid,
        )

    if operation_type == "income":
        return envelope(
            "income_granted",
            {
                "source": income_source_for(name).value,
                "amount": amount,
                "balance_after": balance_after,
            },
        )

    if operation_type == "investment":
        return envelope(
            "savings_deposited",
            {
                "goal_id": goal_id or "unknown",
                "amount": amount,
                "savings_after": savings_after,
                "balance_after": balance_after,
            },
        )

    return envelope(
        "purchase_made",
        {
            # Название операции — это то, что человек написал сам, и оно может
            # оказаться чем угодно. В `item_id` идёт категория, а не текст:
            # свободный ввод пользователя не место в идентификаторе.
            "item_id": f"diary:{(category or 'прочее')}",
            "item_category": expense_category_for(category).value,
            "price": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "effects": [],
        },
    )


def target_to_events(
    *,
    target_uuid: uuid.UUID,
    user_uuid: uuid.UUID,
    target_count: int,
    current_count: int,
    created_at: datetime,
    first_day: date,
    periods_taken: int,
) -> list[dict[str, Any]]:
    """Цель → `goal_selected`, плюс `goal_reached`, если она уже достигнута."""
    profile = profile_pseudo_id(user_uuid)
    day = created_at.date()
    goal_id = f"target:{target_uuid}"

    events = [
        _envelope(
            event_name="goal_selected",
            profile=profile,
            occurred_at=created_at,
            day=day,
            first_day=first_day,
            event_uuid=uuid.uuid5(PROFILE_NAMESPACE, f"target-selected:{target_uuid}"),
            payload={
                "goal_id": goal_id,
                "goal_cost": target_count,
                "savings_at_selection": 0,
            },
        )
    ]

    if current_count >= target_count:
        events.append(
            _envelope(
                event_name="goal_reached",
                profile=profile,
                occurred_at=created_at,
                day=day,
                first_day=first_day,
                event_uuid=uuid.uuid5(PROFILE_NAMESPACE, f"target-reached:{target_uuid}"),
                payload={
                    "goal_id": goal_id,
                    "goal_cost": target_count,
                    "periods_taken": periods_taken,
                },
            )
        )
    return events
