"""Тесты отображения моделей бэкенда в события платформы.

Каждая проверка здесь — про свойство, на которое опирается либо ТЗ, либо
идемпотентность доставки. Ошибка в отображении не уронит ничего сразу: она
тихо запишет неправильные события, а обнаружится на витрине через неделю.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from monetka.common.events import EventEnvelope
from monetka.integration.backend_adapter import (
    ESSENTIAL_CATEGORIES,
    diary_entry_to_event,
    expense_category_for,
    income_source_for,
    period_no_for,
    profile_pseudo_id,
    session_id_for,
    target_to_events,
)

USER = uuid.UUID("11111111-1111-4111-8111-111111111111")
ENTRY = uuid.UUID("22222222-2222-4222-8222-222222222222")
FIRST = date(2026, 7, 2)


def entry(**overrides):
    kwargs = {
        "entry_uuid": ENTRY,
        "user_uuid": USER,
        "operation_type": "expense",
        "name": "Продукты на ужин",
        "category": "Супермаркеты",
        "amount": 450,
        "operation_date": date(2026, 7, 10),
        "occurred_at": datetime(2026, 7, 10, 12, tzinfo=UTC),
        "first_day": FIRST,
        "balance_before": 20_000,
        "balance_after": 19_550,
    }
    kwargs.update(overrides)
    return diary_entry_to_event(**kwargs)


class TestPseudonymisation:
    def test_the_same_user_always_maps_to_the_same_profile(self) -> None:
        """Иначе история профиля рассыплется на куски при каждом переносе."""
        assert profile_pseudo_id(USER) == profile_pseudo_id(USER)
        assert profile_pseudo_id(str(USER)) == profile_pseudo_id(USER)

    def test_different_users_map_to_different_profiles(self) -> None:
        other = uuid.UUID("33333333-3333-4333-8333-333333333333")
        assert profile_pseudo_id(USER) != profile_pseudo_id(other)

    def test_the_profile_id_is_not_the_user_id(self) -> None:
        """ТЗ §3.5: платформа не должна получать ключ, ведущий к человеку."""
        assert profile_pseudo_id(USER) != USER

    def test_no_personal_data_reaches_the_event(self) -> None:
        """Ни email, ни username, ни внутренний id в конверте не появляются."""
        event = entry()
        blob = str(event)
        assert "@" not in blob
        assert str(USER) not in blob


class TestSessionAndPeriod:
    def test_one_session_per_profile_per_day(self) -> None:
        profile = profile_pseudo_id(USER)
        same = session_id_for(profile, date(2026, 7, 10))
        assert same == session_id_for(profile, date(2026, 7, 10))
        assert same != session_id_for(profile, date(2026, 7, 11))

    def test_the_period_counts_months_from_the_first_operation(self) -> None:
        """Отсчёт от первой операции, а не от календаря: иначе у начавшего в
        конце месяца первый период окажется обрезанным."""
        assert period_no_for(FIRST, date(2026, 7, 2)) == 1
        assert period_no_for(FIRST, date(2026, 7, 31)) == 1
        assert period_no_for(FIRST, date(2026, 8, 1)) == 2
        assert period_no_for(FIRST, date(2027, 1, 5)) == 7


class TestCategoryMapping:
    def test_known_essentials_are_essential(self) -> None:
        for category in ESSENTIAL_CATEGORIES:
            assert expense_category_for(category).value == "essential"

    def test_everything_else_is_optional(self) -> None:
        for category in ("Кофейни", "Кино", "Рестораны", "Подарки и сувениры"):
            assert expense_category_for(category).value == "optional"

    def test_an_absent_category_is_optional(self) -> None:
        """Ошибаться безопаснее в сторону «желаемого»: подсказка предложит
        подумать над тратой, а не промолчит о незакрытом необходимом."""
        assert expense_category_for(None).value == "optional"

    def test_regular_income_is_an_allowance(self) -> None:
        for name in ("Зарплата", "Аванс", "Стипендия", "карманные"):
            assert income_source_for(name).value == "period_allowance"

    def test_irregular_income_is_a_bonus(self) -> None:
        assert income_source_for("Подработка").value == "adult_bonus"
        assert income_source_for("").value == "adult_bonus"


class TestEventsAreValid:
    def test_every_operation_type_produces_a_valid_envelope(self) -> None:
        """Событие, не проходящее собственный контракт, будет отвергнуто при
        приёме — и узнаем мы об этом на проде."""
        cases = [
            entry(operation_type="expense"),
            entry(operation_type="income", name="Зарплата", amount=20_000),
            entry(operation_type="investment", amount=300, goal_id="target:x", savings_after=900),
        ]
        for event in cases:
            envelope = EventEnvelope.model_validate(event)
            assert envelope.profile_pseudo_id == profile_pseudo_id(USER)

    def test_device_context_is_absent_not_invented(self) -> None:
        """Ретранслированное событие не приходит с устройства, и подставлять
        правдоподобные значения в типизированные поля нельзя."""
        envelope = EventEnvelope.model_validate(entry())
        assert envelope.app_version is None
        assert envelope.android_api_level is None

    def test_the_event_id_comes_from_the_entry(self) -> None:
        """Повторный перенос не должен удваивать историю."""
        assert entry()["event_id"] == entry()["event_id"]
        other = entry(entry_uuid=uuid.UUID("44444444-4444-4444-8444-444444444444"))
        assert other["event_id"] != entry()["event_id"]

    def test_the_item_id_carries_the_category_not_free_text(self) -> None:
        """Название операции пишет человек, и в идентификаторе ему не место."""
        event = entry(name="Купил что-то; DROP TABLE", category="Кофейни")
        assert event["payload"]["item_id"] == "diary:Кофейни"


class TestTargets:
    def test_an_unfinished_goal_is_only_selected(self) -> None:
        events = target_to_events(
            target_uuid=uuid.uuid4(),
            user_uuid=USER,
            target_count=12_900,
            current_count=8_643,
            created_at=datetime(2026, 7, 2, 7, tzinfo=UTC),
            first_day=FIRST,
            periods_taken=3,
        )
        assert [e["event_name"] for e in events] == ["goal_selected"]

    def test_a_finished_goal_also_reports_reaching_it(self) -> None:
        events = target_to_events(
            target_uuid=uuid.uuid4(),
            user_uuid=USER,
            target_count=12_900,
            current_count=12_900,
            created_at=datetime(2026, 7, 2, 7, tzinfo=UTC),
            first_day=FIRST,
            periods_taken=3,
        )
        assert [e["event_name"] for e in events] == ["goal_selected", "goal_reached"]
        for event in events:
            EventEnvelope.model_validate(event)
