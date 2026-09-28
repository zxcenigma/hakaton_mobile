"""Contract tests for the event schema.

These are the tests that matter most in the repository. The event contract is
what enforces the two guarantees the customer's specification makes about
children's data — that none of it is personal, and that no coin is ever created
or destroyed — so each of those is asserted directly rather than inferred from
downstream behaviour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from monetka.common.events import (
    PAYLOAD_MODELS,
    PET_COMBINATION_COUNT,
    BudgetPlanSubmittedPayload,
    EventEnvelope,
    EventName,
    ExpenseCategory,
    PeriodClosedPayload,
    PersonalDataError,
    PurchaseMadePayload,
    QuestTopic,
    SavingsWithdrawnPayload,
    assert_no_personal_data,
    build_event,
    personal_data_reason,
    validate_event,
)

NOW = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)


def _envelope(name: EventName, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_name=name,
        payload=payload,
        profile_pseudo_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        period_no=1,
        occurred_at=NOW,
        app_version="1.0.0",
        android_api_level=33,
    )


# ------------------------------------------------------------- privacy ------


@pytest.mark.parametrize(
    "field_name",
    [
        "child_name",
        "pet_name",
        "first_name",
        "parent_email",
        "phone_number",
        "birth_date",
        "home_address",
        "latitude",
        "device_id",
        "card_number",
        "passport",
        "snils",
    ],
)
def test_personal_data_fields_are_rejected(field_name: str) -> None:
    with pytest.raises(PersonalDataError):
        assert_no_personal_data({field_name: "anything"})


@pytest.mark.parametrize(
    "field_name",
    [
        # Every one of these contains a forbidden substring and must NOT trip
        # the guard. A guard with false positives is a guard people switch off.
        "cumulative_deposited",  # contains "lat"
        "plan_adherence_volatility",  # contains "lat"
        "startup_latency_ms",  # contains "lat"
        "translation_key",  # contains "lat"
        "event_name",  # explicitly allowed
        "item_category",
        "essential_coverage",
        "goal_cost",
        "savings_after",
    ],
)
def test_safe_fields_are_not_flagged(field_name: str) -> None:
    assert personal_data_reason(field_name) is None, f"{field_name} wrongly flagged"


def test_privacy_guard_recurses_into_nested_objects() -> None:
    with pytest.raises(PersonalDataError, match=r"parent\.email"):
        assert_no_personal_data({"parent": {"email": "a@b.c"}})


def test_envelope_rejects_personal_data_in_payload() -> None:
    with pytest.raises(ValidationError):
        _envelope(EventName.APP_OPENED, {"cold_start": True, "child_name": "Вася"})


# ------------------------------------------------- economy invariants -------


def test_purchase_balance_must_close() -> None:
    """A purchase may not create or destroy coins."""
    with pytest.raises(ValidationError, match="balance_before"):
        PurchaseMadePayload(
            item_id="food_soup",
            item_category=ExpenseCategory.ESSENTIAL,
            price=18,
            balance_before=60,
            balance_after=50,  # should be 42
        )


def test_purchase_cannot_be_categorised_as_savings() -> None:
    with pytest.raises(ValidationError, match="savings are not a purchase"):
        PurchaseMadePayload(
            item_id="food_soup",
            item_category=ExpenseCategory.SAVINGS,
            price=10,
            balance_before=50,
            balance_after=40,
        )


def test_plan_cannot_exceed_available_budget() -> None:
    """ТЗ §2.5.5 — the app must not allow over-allocation."""
    with pytest.raises(ValidationError, match="plan allocates"):
        BudgetPlanSubmittedPayload(
            available_total=60,
            planned_essential=30,
            planned_optional=30,
            planned_savings=10,
            revisions_count=0,
            seconds_spent=30,
        )


def test_plan_may_leave_coins_unallocated() -> None:
    plan = BudgetPlanSubmittedPayload(
        available_total=60,
        planned_essential=24,
        planned_optional=10,
        planned_savings=16,
        revisions_count=1,
        seconds_spent=40,
    )
    assert plan.unallocated == 10


def test_negative_balance_is_unrepresentable() -> None:
    """ТЗ §2.5.6 — a negative balance must be impossible, not merely avoided."""
    with pytest.raises(ValidationError):
        PurchaseMadePayload(
            item_id="deco_lamp",
            item_category=ExpenseCategory.OPTIONAL,
            price=40,
            balance_before=10,
            balance_after=-30,
        )


def test_withdrawal_requires_explicit_confirmation() -> None:
    """ТЗ §2.5.7 — withdrawing from a goal needs a separate confirmation."""
    with pytest.raises(ValidationError):
        SavingsWithdrawnPayload(
            goal_id="goal_scooter",
            amount=20,
            savings_after=80,
            balance_after=50,
            confirmed=False,  # only True is representable
        )


# ------------------------------------------------------- plan adherence -----


def test_plan_adherence_is_one_when_fact_matches_plan() -> None:
    closed = PeriodClosedPayload(
        closed_period_no=1,
        available_total=100,
        planned_essential=50,
        planned_optional=20,
        planned_savings=30,
        actual_essential=50,
        actual_optional=20,
        actual_savings=30,
        essential_coverage=1.0,
        leftover=0,
    )
    assert closed.plan_adherence == 1.0


def test_plan_adherence_never_goes_below_zero() -> None:
    """A wildly off plan floors at 0 rather than going negative — the number is
    shown to a child, and a negative score would need explaining."""
    closed = PeriodClosedPayload(
        closed_period_no=1,
        available_total=100,
        planned_essential=10,
        planned_optional=10,
        planned_savings=10,
        actual_essential=90,
        actual_optional=0,
        actual_savings=0,
        essential_coverage=1.0,
        leftover=10,
    )
    assert closed.plan_adherence == 0.0


# ----------------------------------------------------------- envelope -------


def test_occurred_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EventEnvelope(
            event_name=EventName.APP_OPENED,
            payload={},
            profile_pseudo_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            period_no=0,
            occurred_at=datetime(2026, 3, 5, 12, 0),  # naive
            app_version="1.0.0",
            android_api_level=33,
        )


def test_android_api_level_floor_matches_tz() -> None:
    """ТЗ §3.1.1 — Android 8.0 (API 26) is the minimum supported version."""
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_name=EventName.APP_OPENED,
            payload={},
            profile_pseudo_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            period_no=0,
            occurred_at=NOW,
            app_version="1.0.0",
            android_api_level=25,
        )


def test_app_version_must_be_semver() -> None:
    with pytest.raises(ValueError, match="semver"):
        build_event(
            event_name=EventName.APP_OPENED,
            payload=PAYLOAD_MODELS[EventName.APP_OPENED](cold_start=True, startup_latency_ms=100),
            profile_pseudo_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            period_no=0,
            occurred_at=NOW,
            app_version="1.0",
        )


def test_every_event_name_has_a_payload_contract() -> None:
    """A new event without a contract would land in bronze and never reach silver."""
    missing = set(EventName) - set(PAYLOAD_MODELS)
    assert not missing, f"no payload contract for: {sorted(e.value for e in missing)}"


def test_validate_event_returns_the_typed_payload() -> None:
    envelope = _envelope(EventName.APP_OPENED, {"cold_start": True, "startup_latency_ms": 1200})
    payload = validate_event(envelope)
    assert payload.startup_latency_ms == 1200


def test_partition_date_follows_occurred_at() -> None:
    envelope = _envelope(EventName.APP_OPENED, {"cold_start": True, "startup_latency_ms": 10})
    assert envelope.partition_date() == "2026-03-05"


def test_ingested_at_is_preserved_when_supplied() -> None:
    """Backfills carry their original delivery time; it must survive the round trip."""
    delivered = NOW + timedelta(hours=5)
    envelope = build_event(
        event_name=EventName.APP_OPENED,
        payload=PAYLOAD_MODELS[EventName.APP_OPENED](cold_start=True, startup_latency_ms=800),
        profile_pseudo_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        period_no=0,
        occurred_at=NOW,
        ingested_at=delivered,
    )
    assert envelope.ingested_at == delivered


# --------------------------------------------------------- ТЗ minimums ------


def test_pet_combination_count_meets_specification() -> None:
    """ТЗ §2.6 — «не менее 9 визуально различимых комбинаций»."""
    assert PET_COMBINATION_COUNT >= 9


def test_three_mandatory_quest_topics_exist() -> None:
    """ТЗ §2.5.8 — budgeting, saving, payments."""
    assert {t.value for t in QuestTopic} == {"budgeting", "saving", "payments"}
