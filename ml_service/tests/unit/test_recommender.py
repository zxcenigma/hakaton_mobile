"""Tests for the deterministic decision layer.

This is where the specification's hard constraints are enforced, so these tests
are the ones that would catch a model quietly overriding pedagogy. Each asserts
a rule the model is *not permitted* to break, and every rule is checked both
with and without model scores present — because the no-model path is what runs
on a device that failed to load the ONNX file.
"""

from __future__ import annotations

import pytest

from monetka.common.content import ContentPack
from monetka.common.events import QuestTopic
from monetka.serving.recommender import (
    HINTS,
    MAX_DIFFICULTY,
    PeriodSnapshot,
    Segment,
    hint_for,
    max_difficulty_for,
    recommend_quests,
    rule_based_hint,
)


def snapshot(**overrides) -> PeriodSnapshot:
    base = {
        "essential_coverage": 1.0,
        "plan_adherence": 0.9,
        "savings_rate": 0.2,
        "rejected_purchases": 0,
        "periods_completed": 3,
    }
    return PeriodSnapshot(**{**base, **overrides})


# ------------------------------------------------------------- hints --------


def test_uncovered_essentials_always_win() -> None:
    """Whatever else happened, an unfed pet is the most important thing to say."""
    hint = rule_based_hint(snapshot(essential_coverage=0.4, plan_adherence=1.0, savings_rate=0.5))
    assert hint.hint_id in {"essentials_first", "saving_but_hungry"}


def test_saving_while_hungry_gets_its_own_message() -> None:
    hint = rule_based_hint(snapshot(essential_coverage=0.4, savings_rate=0.4))
    assert hint.hint_id == "saving_but_hungry"


def test_blocked_purchase_is_framed_as_a_choice_not_a_failure() -> None:
    hint = rule_based_hint(snapshot(rejected_purchases=2))
    assert hint.hint_id == "try_cheaper"
    assert "не ошибка" in hint.next_step


def test_no_savings_prompts_a_small_first_step() -> None:
    hint = rule_based_hint(snapshot(savings_rate=0.0))
    assert hint.hint_id == "start_saving"


def test_every_hint_states_a_next_step() -> None:
    """ТЗ §2.5.9 — feedback explains the consequence *and* offers a way forward."""
    for hint in HINTS.values():
        assert hint.text.strip(), f"{hint.hint_id} has no text"
        assert hint.next_step.strip(), f"{hint.hint_id} offers no next step"


def test_model_cannot_override_a_concrete_problem() -> None:
    """The model may refine wording, never contradict a rule.

    Even when the segment suggests a different message, an uncovered essential
    must still produce the essentials hint.
    """
    problem = snapshot(essential_coverage=0.3, savings_rate=0.0)
    for segment in Segment:
        hint = hint_for(problem, segment)
        assert hint.hint_id == "essentials_first", f"segment {segment} overrode the rule"
        assert hint.source == "rule"


def test_model_may_refine_wording_when_rules_are_indifferent() -> None:
    fine = snapshot(essential_coverage=1.0, plan_adherence=0.95, savings_rate=0.3)
    default = hint_for(fine, Segment.UNKNOWN)
    refined = hint_for(fine, Segment.EXPLORER)
    assert default.source == "rule"
    assert refined.source == "model"
    assert refined.hint_id == "explore_steady"


def test_unknown_segment_falls_back_to_rules() -> None:
    """The offline path: no model loaded, full answer still produced."""
    for coverage in (0.2, 0.5, 0.9, 1.0):
        hint = hint_for(snapshot(essential_coverage=coverage), Segment.UNKNOWN)
        assert hint.source == "rule"
        assert hint.text


# -------------------------------------------------------- difficulty --------


@pytest.mark.parametrize(
    ("periods", "expected"),
    [(0, 1), (1, 1), (2, 2), (3, 2), (4, 3), (12, 3), (100, 3)],
)
def test_difficulty_ladder(periods: int, expected: int) -> None:
    assert max_difficulty_for(periods) == expected


def test_difficulty_never_exceeds_the_ceiling() -> None:
    for periods in range(0, 200):
        assert max_difficulty_for(periods) <= MAX_DIFFICULTY


def test_beginner_is_never_offered_a_hard_quest(content: ContentPack) -> None:
    """ТЗ §3.6 — complexity must suit the age, and a model must not push past it."""
    # A model that loves the hardest quest cannot get it past the rule.
    adversarial = {q.id: 100.0 if q.difficulty == 3 else 0.0 for q in content.quests}
    chosen = recommend_quests(
        completed_quest_ids=set(),
        topic_scores={},
        periods_completed=0,
        model_scores=adversarial,
        content=content,
    )
    assert chosen
    assert all(q.difficulty <= 1 for q in chosen)


# ---------------------------------------------------- topic coverage --------


def test_all_three_topics_are_reachable(content: ContentPack) -> None:
    """ТЗ §2.5.8 — the three mandatory topics must all surface."""
    chosen = recommend_quests(
        completed_quest_ids=set(),
        topic_scores={},
        periods_completed=8,
        limit=3,
        content=content,
    )
    assert {q.topic for q in chosen} == set(QuestTopic)


def test_weakest_topic_comes_first(content: ContentPack) -> None:
    chosen = recommend_quests(
        completed_quest_ids=set(),
        topic_scores={
            QuestTopic.BUDGETING: 0.9,
            QuestTopic.PAYMENTS: 0.9,
            QuestTopic.SAVING: 0.1,
        },
        periods_completed=8,
        limit=3,
        content=content,
    )
    assert chosen[0].topic is QuestTopic.SAVING


def test_a_dominant_model_cannot_starve_a_topic(content: ContentPack) -> None:
    """A recommender that adores one topic still cannot monopolise the slate."""
    budgeting_only = {
        q.id: (100.0 if q.topic is QuestTopic.BUDGETING else -100.0) for q in content.quests
    }
    chosen = recommend_quests(
        completed_quest_ids=set(),
        topic_scores={},
        periods_completed=8,
        model_scores=budgeting_only,
        limit=3,
        content=content,
    )
    assert len({q.topic for q in chosen}) == 3


def test_unseen_quests_are_preferred(content: ContentPack) -> None:
    completed = {q.id for q in content.quests_by_topic(QuestTopic.SAVING)[:1]}
    chosen = recommend_quests(
        completed_quest_ids=completed,
        topic_scores={QuestTopic.SAVING: 0.0},
        periods_completed=8,
        limit=1,
        content=content,
    )
    assert chosen[0].id not in completed


def test_recommendation_works_without_a_model(content: ContentPack) -> None:
    """The fallback path must return a complete, valid slate."""
    chosen = recommend_quests(
        completed_quest_ids=set(),
        topic_scores={},
        periods_completed=5,
        model_scores=None,
        limit=3,
        content=content,
    )
    assert len(chosen) == 3
    assert all(q.difficulty <= max_difficulty_for(5) for q in chosen)


def test_recommendation_is_never_empty(content: ContentPack) -> None:
    """Even a brand-new profile with nothing played must get something."""
    for periods in (0, 1, 5, 50):
        chosen = recommend_quests(
            completed_quest_ids={q.id for q in content.quests},
            topic_scores={},
            periods_completed=periods,
            content=content,
        )
        assert chosen, f"no quest offered at period {periods}"
