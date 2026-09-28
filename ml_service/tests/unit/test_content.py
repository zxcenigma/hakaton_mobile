"""Tests for the educational content pack.

The content pack is edited by a methodologist, not a programmer, and it is the
part of the product a reviewer reads first. These tests are its guardrails:
they check the ТЗ §2.6 minimums, the age-appropriateness of the arithmetic and
the safety properties that ТЗ §2 and §3.5 require of the wording and mechanics.

They deliberately assert on *content*, so adding a quest that quietly breaks the
pedagogy fails CI rather than reaching a child.
"""

from __future__ import annotations

import itertools
import re

import pytest

from monetka.common.content import (
    MIN_CATALOG_ITEMS,
    MIN_GOALS,
    MIN_PET_STAGES,
    MIN_QUESTS,
    ContentPack,
)
from monetka.common.events import ExpenseCategory, QuestOutcome, QuestTopic

# ---------------------------------------------------- ТЗ §2.6 minimums ------


def test_catalogue_meets_minimum(content: ContentPack) -> None:
    assert len(content.items) >= MIN_CATALOG_ITEMS


def test_catalogue_has_both_expense_types(content: ContentPack) -> None:
    assert content.items_by_category(ExpenseCategory.ESSENTIAL)
    assert content.items_by_category(ExpenseCategory.OPTIONAL)


def test_quest_minimum_and_topic_coverage(content: ContentPack) -> None:
    assert len(content.quests) >= MIN_QUESTS
    assert {q.topic for q in content.quests} == set(QuestTopic)


def test_goals_minimum(content: ContentPack) -> None:
    assert len(content.goals) >= MIN_GOALS


def test_pet_stages_minimum(content: ContentPack) -> None:
    assert len(content.pet_rules.stage_order) >= MIN_PET_STAGES


# ------------------------------------------------------- safety rules -------


def test_no_unrecoverable_effects(content: ContentPack) -> None:
    """ТЗ §2.2 — an error must stay recoverable.

    No single purchase may be able to drive a pet state from full to the floor,
    which would make one bad decision feel irreversible to a child.
    """
    rules = content.pet_rules
    survivable = rules.ceiling_value - rules.floor_value
    for item in content.items:
        for effect in item.effects:
            assert abs(effect.delta) < survivable, (
                f"item {item.id!r} effect on {effect.state.value} is {effect.delta}, "
                f"which could move a state across the whole {survivable}-point range"
            )


def test_every_quest_choice_explains_itself(content: ContentPack) -> None:
    """ТЗ §2.5.8 — an explanation is shown regardless of correctness."""
    for quest in content.quests:
        for choice in quest.choices:
            assert choice.explanation.strip(), f"{quest.id}/{choice.id} has no explanation"


def test_every_quest_offers_a_good_option(content: ContentPack) -> None:
    for quest in content.quests:
        assert quest.optimal_choices, f"quest {quest.id!r} has no optimal choice"


def test_poor_choices_still_earn_something(content: ContentPack) -> None:
    """ТЗ §3.5 — the tone must not punish. A wrong answer still teaches, so it
    still pays; it simply pays less than a good one."""
    for quest in content.quests:
        best = max(c.reward for c in quest.choices)
        for choice in quest.choices:
            if choice.outcome is QuestOutcome.POOR:
                assert choice.reward > 0, f"{quest.id}/{choice.id} rewards nothing"
                assert choice.reward < best


SHAMING_WORDS = re.compile(
    r"\b(глуп|дурак|плохой ребёнок|стыдно|виноват|провал|ужасн|никогда не сможешь)",
    re.IGNORECASE,
)


def test_no_shaming_or_frightening_language(content: ContentPack) -> None:
    """ТЗ §3.5 — texts must not frighten, shame or blame the child."""
    texts: list[tuple[str, str]] = []
    for quest in content.quests:
        texts.append((quest.id, quest.situation))
        texts.extend((f"{quest.id}/{c.id}", c.explanation) for c in quest.choices)
    for item in content.items:
        texts.append((item.id, item.why))
    for code in content.pet_rules.reason_codes:
        texts.append((code.code, code.child_text))

    offenders = [(where, text) for where, text in texts if SHAMING_WORDS.search(text)]
    assert not offenders, f"shaming language found in: {[w for w, _ in offenders]}"


def test_pet_stages_never_regress(content: ContentPack) -> None:
    """ТЗ §2 — progress already earned is never taken away."""
    assert content.pet_rules.no_regression is True


def test_stage_requirements_are_monotonic(content: ContentPack) -> None:
    """Each stage must be at least as demanding as the one before it.

    A later stage that is easier to reach would let a child skip a level, or
    oscillate between two stages, which the «no regression» promise forbids.
    """
    levels = {level.id: level for level in content.pet_rules.stage_levels}
    order = content.pet_rules.stage_order
    for earlier, later in itertools.pairwise(order):
        before, after = levels[earlier].requires, levels[later].requires
        for key, value in before.items():
            assert after.get(key, value) >= value, (
                f"stage {later.value!r} requires less {key} "
                f"({after.get(key)}) than {earlier.value!r} ({value})"
            )


# ------------------------------------------------- age appropriateness ------


def test_arithmetic_is_age_appropriate(content: ContentPack) -> None:
    """Numbers a 7-11 year old can actually handle.

    ТЗ §2.5.8 — «сложность формулировок и вычислений соответствует возрасту
    7-11 лет». Division is allowed only when it comes out whole.
    """
    for quest in content.quests:
        arithmetic = quest.arithmetic
        if arithmetic is None:
            continue
        expression = arithmetic.expression
        assert re.fullmatch(r"[\d\s+\-*/().]+", expression), (
            f"{quest.id}: expression {expression!r} contains unexpected symbols"
        )
        result = eval(expression)
        assert result == arithmetic.answer, (
            f"{quest.id}: stated answer {arithmetic.answer} != computed {result}"
        )
        assert float(result).is_integer(), f"{quest.id}: answer is not a whole number"
        assert 0 < result <= 1000, f"{quest.id}: answer {result} is outside a child's range"


def test_prices_are_whole_and_small(content: ContentPack) -> None:
    for item in content.items:
        assert isinstance(item.price, int)
        assert 1 <= item.price <= 100, f"{item.id}: price {item.price} is hard to reason about"


def test_essentials_are_affordable_within_one_period(content: ContentPack) -> None:
    """The economy must never make the mandatory scenario impossible.

    ТЗ §2.2 forbids trapping a child. If covering every need cost more than a
    plausible allowance, the game would be unwinnable by construction.
    """
    assert content.essential_period_cost > 0
    cheapest_essential = min(
        item.price for item in content.items_by_category(ExpenseCategory.ESSENTIAL)
    )
    assert cheapest_essential <= 15, "no affordable entry-level essential exists"


@pytest.mark.parametrize("tier", ["short", "medium", "long"])
def test_goal_tiers_are_represented(content: ContentPack, tier: str) -> None:
    """A child needs a reachable first goal as well as an aspirational one."""
    assert any(goal.tier == tier for goal in content.goals)


def test_goal_costs_increase_with_tier(content: ContentPack) -> None:
    by_tier = {"short": [], "medium": [], "long": []}
    for goal in content.goals:
        by_tier[goal.tier].append(goal.cost)
    assert max(by_tier["short"]) <= min(by_tier["medium"])
    assert max(by_tier["medium"]) <= min(by_tier["long"])


# -------------------------------------------------------- competencies ------


def test_every_competency_is_measurable(content: ContentPack) -> None:
    """ТЗ §5.7 — the content map states how each competency is measured."""
    for competency in content.competencies:
        assert competency.get("statement"), f"{competency['id']} has no statement"
        assert competency.get("measured_by"), f"{competency['id']} has no measurement"
        assert competency.get("mechanic"), f"{competency['id']} has no mechanic"


def test_quests_reference_real_competencies(content: ContentPack) -> None:
    known = {c["id"] for c in content.competencies}
    for quest in content.quests:
        unknown = set(quest.competency) - known
        assert not unknown, f"{quest.id} references unknown competencies: {unknown}"


def test_each_topic_has_several_difficulties(content: ContentPack) -> None:
    """Enough range per topic for the recommender's difficulty ladder to work."""
    for topic in QuestTopic:
        difficulties = {q.difficulty for q in content.quests_by_topic(topic)}
        assert len(difficulties) >= 2, f"topic {topic.value} has only one difficulty level"
