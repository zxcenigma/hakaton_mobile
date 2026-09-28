"""Tests for the synthetic telemetry simulator.

The simulator is the source of every row the platform is built and validated on,
so a bug here silently invalidates every downstream metric. These tests assert
the properties the rest of the platform assumes: determinism, economy
invariants, and that the modelled learning effect is actually present.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from monetka.common.events import EventName, ExpenseCategory
from monetka.generator.simulator import ARCHETYPE_WEIGHTS, Simulator

START = datetime(2026, 1, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def events():
    simulator = Simulator(seed=7)
    return list(simulator.simulate_cohort(30, 8, START)), simulator


def test_simulation_is_deterministic() -> None:
    """Same seed, same data — otherwise nothing downstream is reproducible."""
    first = [e.event_name for e in Simulator(seed=99).simulate_cohort(5, 4, START)]
    second = [e.event_name for e in Simulator(seed=99).simulate_cohort(5, 4, START)]
    assert first == second


def test_different_seeds_produce_different_data() -> None:
    first = list(Simulator(seed=1).simulate_cohort(5, 4, START))
    second = list(Simulator(seed=2).simulate_cohort(5, 4, START))
    assert len(first) != len(second) or first[0].profile_pseudo_id != second[0].profile_pseudo_id


def test_every_event_validates_against_its_contract(events) -> None:
    from monetka.common.events import validate_event

    stream, _ = events
    for event in stream:
        validate_event(event)  # raises if the payload breaks its contract


def test_labels_cover_every_profile(events) -> None:
    stream, simulator = events
    profiles = {str(e.profile_pseudo_id) for e in stream}
    assert profiles == set(simulator.labels)


def test_ground_truth_label_is_not_present_in_telemetry(events) -> None:
    """The archetype must never leak into the event stream.

    One event legitimately carries a segment: `hint_shown` records what the
    model *predicted*, which is real production telemetry needed for monitoring.
    Every other event must be free of it — a model that learned the label from
    an unrelated event would be reading something that does not exist at
    inference time.
    """
    stream, simulator = events
    archetypes = set(simulator.labels.values())
    for event in stream:
        if event.event_name is EventName.HINT_SHOWN:
            continue
        flat = str(event.payload).lower()
        for archetype in archetypes:
            assert archetype not in flat, f"archetype {archetype!r} leaked into {event.event_name}"


def test_predicted_segment_is_a_prediction_not_the_label(events) -> None:
    """`hint_shown.predicted_segment` must disagree with the truth sometimes.

    If it always matched, it would be the ground-truth label wearing a
    prediction's name: monitoring would report a perfect model, and anything
    trained on it would leak.
    """
    stream, simulator = events
    compared = 0
    disagreements = 0
    for event in stream:
        if event.event_name is not EventName.HINT_SHOWN:
            continue
        predicted = event.payload.get("predicted_segment")
        if predicted is None:
            continue  # rule-based hint: no model involved
        compared += 1
        if predicted != simulator.labels[str(event.profile_pseudo_id)]:
            disagreements += 1

    assert compared > 0, "no model-attributed hints were produced"
    error_rate = disagreements / compared
    # The simulated model is ~89% accurate inside its horizon and worse outside.
    assert 0.03 < error_rate < 0.45, f"implausible simulated error rate: {error_rate:.2%}"


def test_predicted_segment_is_not_a_training_feature() -> None:
    """Training on the model's own past output would be self-referential."""
    from monetka.ml.features import BEHAVIOUR_FEATURES

    assert "predicted_segment" not in BEHAVIOUR_FEATURES
    assert not any("segment" in name for name in BEHAVIOUR_FEATURES)


def test_all_archetypes_are_represented(events) -> None:
    _, simulator = events
    assert set(simulator.labels.values()) == set(ARCHETYPE_WEIGHTS)


# --------------------------------------------------- economy invariants -----


def test_balance_never_goes_negative(events) -> None:
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.PURCHASE_MADE:
            assert event.payload["balance_after"] >= 0


def test_purchase_arithmetic_always_closes(events) -> None:
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.PURCHASE_MADE:
            payload = event.payload
            assert payload["balance_before"] - payload["price"] == payload["balance_after"]


def test_rejected_purchases_were_genuinely_unaffordable(events) -> None:
    """ТЗ §2.5.6 — a rejection must be explainable by a real shortfall."""
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.PURCHASE_REJECTED:
            payload = event.payload
            if payload["reason"] == "insufficient_balance":
                assert payload["price"] > payload["balance"]


def test_plans_never_over_allocate(events) -> None:
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.BUDGET_PLAN_SUBMITTED:
            payload = event.payload
            allocated = (
                payload["planned_essential"]
                + payload["planned_optional"]
                + payload["planned_savings"]
            )
            assert allocated <= payload["available_total"]


def test_pet_stage_only_moves_forward(events) -> None:
    from monetka.common.content import get_content

    order = [s.value for s in get_content().pet_rules.stage_order]
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.PET_STAGE_CHANGED:
            payload = event.payload
            assert order.index(payload["stage_after"]) > order.index(payload["stage_before"])


def test_pet_state_never_falls_below_floor(events) -> None:
    from monetka.common.content import get_content

    floor = get_content().pet_rules.floor_value
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.PET_STATE_CHANGED:
            assert event.payload["value_after"] >= floor


def test_income_is_always_attributed(events) -> None:
    """ТЗ §2.5.4 — the balance never changes without a stated source."""
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.INCOME_GRANTED:
            assert event.payload["source"]
            assert event.payload["amount"] > 0


def test_withdrawals_are_always_confirmed(events) -> None:
    stream, _ = events
    for event in stream:
        if event.event_name is EventName.SAVINGS_WITHDRAWN:
            assert event.payload["confirmed"] is True


# ------------------------------------------------------- data properties ----


def test_every_period_closes(events) -> None:
    stream, _ = events
    plans = Counter(
        (str(e.profile_pseudo_id), e.period_no)
        for e in stream
        if e.event_name is EventName.BUDGET_PLAN_SUBMITTED
    )
    closes = Counter(
        (str(e.profile_pseudo_id), e.period_no)
        for e in stream
        if e.event_name is EventName.PERIOD_CLOSED
    )
    assert set(plans) == set(closes)


def test_delivery_delay_produces_a_realistic_late_tail(events) -> None:
    """Some events arrive days late; most arrive immediately.

    The late-arrival quality check and the DAG's lookback window both exist to
    handle this, so the generator has to actually produce it.
    """
    stream, _ = events
    delays = [
        (e.ingested_at - e.occurred_at).total_seconds() for e in stream if e.ingested_at is not None
    ]
    assert delays, "no ingestion timestamps were produced"
    immediate = sum(1 for d in delays if d <= 120)
    very_late = sum(1 for d in delays if d > 12 * 3600)
    assert immediate / len(delays) > 0.5, "most events should arrive promptly"
    assert very_late > 0, "the offline tail is missing"


def test_children_improve_over_time(events) -> None:
    """The modelled learning effect must actually show up in the data.

    Without it the dataset is stationary, the drift monitor has nothing to
    detect and the behaviour model's decay finding would be an artefact.
    """
    stream, _ = events
    by_period: dict[int, list[float]] = {}
    for event in stream:
        if event.event_name is EventName.PERIOD_CLOSED:
            by_period.setdefault(event.payload["closed_period_no"], []).append(
                event.payload["essential_coverage"]
            )
    early = sum(by_period[1]) / len(by_period[1])
    late = sum(by_period[8]) / len(by_period[8])
    assert late > early, f"coverage did not improve: period 1 {early:.3f} → period 8 {late:.3f}"


def test_both_expense_categories_are_exercised(events) -> None:
    stream, _ = events
    categories = {
        e.payload["item_category"] for e in stream if e.event_name is EventName.PURCHASE_MADE
    }
    assert categories == {ExpenseCategory.ESSENTIAL.value, ExpenseCategory.OPTIONAL.value}


def test_demo_traffic_is_absent_by_default(events) -> None:
    stream, _ = events
    assert not any(e.demo_mode for e in stream)
