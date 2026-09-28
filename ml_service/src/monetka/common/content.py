"""Typed loader for the educational content pack.

The content pack (``content/*.yaml``) is deliberately data, not code: a
methodologist adds a quest or a catalogue item by editing YAML, and neither the
Android app nor this platform needs a rebuild (ТЗ §2.5.14, §3.2 «учебный контент
должен быть отделён от интерфейсного кода»).

This module is the only place that knows the YAML layout. Everything else works
with the typed objects below, so a schema change surfaces as a test failure
rather than a ``KeyError`` deep inside a DAG.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from monetka.common.config import REPO_ROOT
from monetka.common.events import (
    ExpenseCategory,
    PetStage,
    PetStateKind,
    QuestOutcome,
    QuestTopic,
)

CONTENT_DIR = REPO_ROOT / "content"

# Minimums mandated by ТЗ §2.6 «Минимальный объём демонстрационного контента».
MIN_CATALOG_ITEMS = 8
MIN_QUESTS = 6
MIN_QUEST_TOPICS = 3
MIN_GOALS = 3
MIN_PET_STAGES = 3


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StateEffect(_Frozen):
    state: PetStateKind
    delta: int = Field(ge=-50, le=50)


class CatalogItem(_Frozen):
    id: str
    category: ExpenseCategory
    price: int = Field(gt=0)
    child_label: str
    why: str
    period_need: int = 0
    unexpected: bool = False
    effects: list[StateEffect] = Field(default_factory=list)


class QuestChoice(_Frozen):
    id: str
    label: str
    outcome: QuestOutcome
    reward: int = Field(ge=0)
    explanation: str
    pet_effect: StateEffect | None = None

    @model_validator(mode="after")
    def _explanation_is_always_present(self) -> QuestChoice:
        # ТЗ §2.5.8 — объяснение показывается независимо от правильности.
        if not self.explanation.strip():
            raise ValueError(f"choice {self.id!r} has no explanation")
        return self


class QuestArithmetic(_Frozen):
    expression: str
    answer: int


class Quest(_Frozen):
    id: str
    topic: QuestTopic
    difficulty: int = Field(ge=1, le=3)
    title: str
    situation: str
    competency: list[str] = Field(default_factory=list)
    arithmetic: QuestArithmetic | None = None
    choices: list[QuestChoice] = Field(min_length=2)

    @model_validator(mode="after")
    def _has_a_recoverable_path(self) -> Quest:
        outcomes = {c.outcome for c in self.choices}
        if QuestOutcome.OPTIMAL not in outcomes:
            raise ValueError(f"quest {self.id!r} offers no optimal choice")
        return self

    @property
    def optimal_choices(self) -> list[QuestChoice]:
        return [c for c in self.choices if c.outcome is QuestOutcome.OPTIMAL]


class Goal(_Frozen):
    id: str
    cost: int = Field(gt=0)
    child_label: str
    hint: str
    tier: str


class StageLevel(_Frozen):
    id: PetStage
    child_label: str
    requires: dict[str, float] = Field(default_factory=dict)


class ReasonCode(_Frozen):
    code: str
    child_text: str


class PetRules(_Frozen):
    floor_value: int
    ceiling_value: int
    initial_value: int
    decay_per_period: dict[PetStateKind, int]
    stage_order: list[PetStage]
    stage_levels: list[StageLevel]
    evaluation_window_periods: int
    no_regression: bool
    reason_codes: list[ReasonCode]

    def stage_for(self, metrics: dict[str, float]) -> PetStage:
        """Highest stage whose requirements are all satisfied.

        Walks the ladder from the top down and returns the first stage the
        player qualifies for; ``hatchling`` is the floor, so a player can never
        fall out of the progression (ТЗ §2 — прогресс не обнуляется).
        """
        by_id = {level.id: level for level in self.stage_levels}
        for stage in reversed(self.stage_order):
            level = by_id[stage]
            if all(metrics.get(key, 0.0) >= threshold for key, threshold in level.requires.items()):
                return stage
        return self.stage_order[0]


class ContentPack(_Frozen):
    """The whole educational content pack, validated as one unit."""

    items: list[CatalogItem]
    quests: list[Quest]
    goals: list[Goal]
    pet_rules: PetRules
    competencies: list[dict[str, Any]]

    # ------------------------------------------------------------ lookups --
    @functools.cached_property
    def items_by_id(self) -> dict[str, CatalogItem]:
        return {item.id: item for item in self.items}

    @functools.cached_property
    def quests_by_id(self) -> dict[str, Quest]:
        return {quest.id: quest for quest in self.quests}

    @functools.cached_property
    def goals_by_id(self) -> dict[str, Goal]:
        return {goal.id: goal for goal in self.goals}

    def items_by_category(self, category: ExpenseCategory) -> list[CatalogItem]:
        return [item for item in self.items if item.category is category]

    def quests_by_topic(self, topic: QuestTopic) -> list[Quest]:
        return [quest for quest in self.quests if quest.topic is topic]

    @property
    def essential_period_cost(self) -> int:
        """Cost of covering every mandatory need once per period.

        Used to size the starting allowance so that the mandatory scenario is
        always completable — a child must never be placed in a position where
        essentials are unaffordable by construction.
        """
        return sum(item.price * item.period_need for item in self.items)

    # --------------------------------------------------- ТЗ §2.6 minimums --
    @model_validator(mode="after")
    def _meets_mandatory_minimums(self) -> ContentPack:
        problems: list[str] = []
        if len(self.items) < MIN_CATALOG_ITEMS:
            problems.append(
                f"catalogue has {len(self.items)} items, ТЗ §2.6 requires ≥{MIN_CATALOG_ITEMS}"
            )
        categories = {item.category for item in self.items}
        if not {ExpenseCategory.ESSENTIAL, ExpenseCategory.OPTIONAL} <= categories:
            problems.append("catalogue must contain both essential and optional items")
        if len(self.quests) < MIN_QUESTS:
            problems.append(f"{len(self.quests)} quests, ТЗ §2.6 requires ≥{MIN_QUESTS}")
        topics = {quest.topic for quest in self.quests}
        if len(topics) < MIN_QUEST_TOPICS:
            problems.append(
                f"quests cover {len(topics)} topics, ТЗ §2.5.8 requires ≥{MIN_QUEST_TOPICS}"
            )
        if len(self.goals) < MIN_GOALS:
            problems.append(f"{len(self.goals)} goals, ТЗ §2.6 requires ≥{MIN_GOALS}")
        if len(self.pet_rules.stage_order) < MIN_PET_STAGES:
            problems.append(
                f"{len(self.pet_rules.stage_order)} pet stages, ТЗ §2.6 requires ≥{MIN_PET_STAGES}"
            )
        if problems:
            raise ValueError("content pack violates ТЗ §2.6:\n  - " + "\n  - ".join(problems))
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_content(content_dir: Path | None = None) -> ContentPack:
    """Load and validate the content pack. Raises on any ТЗ §2.6 shortfall."""
    directory = content_dir or CONTENT_DIR

    items_raw = _read_yaml(directory / "catalog_items.yaml")["items"]
    quests_raw = _read_yaml(directory / "quests.yaml")["quests"]
    goals_raw = _read_yaml(directory / "goals.yaml")["goals"]
    rules_raw = _read_yaml(directory / "pet_rules.yaml")
    competencies_raw = _read_yaml(directory / "competencies.yaml")["competencies"]

    pet_rules = PetRules(
        floor_value=rules_raw["states"]["floor_value"],
        ceiling_value=rules_raw["states"]["ceiling_value"],
        initial_value=rules_raw["states"]["initial_value"],
        decay_per_period=rules_raw["states"]["decay_per_period"],
        stage_order=rules_raw["stages"]["order"],
        stage_levels=[StageLevel(**level) for level in rules_raw["stages"]["levels"]],
        evaluation_window_periods=rules_raw["stages"]["evaluation_window_periods"],
        no_regression=rules_raw["stages"]["no_regression"],
        reason_codes=[ReasonCode(**rc) for rc in rules_raw["reason_codes"]],
    )

    return ContentPack(
        items=[CatalogItem(**item) for item in items_raw],
        quests=[Quest(**quest) for quest in quests_raw],
        goals=[Goal(**goal) for goal in goals_raw],
        pet_rules=pet_rules,
        competencies=competencies_raw,
    )


@functools.lru_cache(maxsize=1)
def get_content() -> ContentPack:
    """Cached content pack for the current process."""
    return load_content()
