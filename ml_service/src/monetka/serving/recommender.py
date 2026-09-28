"""The deterministic parts of the product: hints and quest selection.

This module is where the boundary between «model» and «product» is drawn, and
it is drawn on purpose.

A model produces a *score*. This module turns scores into decisions, and it is
the only thing allowed to. Every hard constraint from the specification is
enforced here, in plain Python that a reviewer can read end to end:

* age-appropriate difficulty is never exceeded (ТЗ §2.5.8, §3.6);
* all three mandatory topics are reachable, so a recommender that liked one
  topic could not starve the other two (ТЗ §2.5.8);
* every hint pairs a consequence with a next step, never a bare judgement
  (ТЗ §2.5.9);
* the wording never shames or frightens (ТЗ §3.5).

If a model is unavailable, these rules still produce a complete answer. That is
the fallback: the product degrades to «no personalisation», never to «no hint».
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from monetka.common.content import ContentPack, Quest, get_content
from monetka.common.events import QuestTopic

#: Difficulty a child may be offered, by how many periods they have played.
#: Deliberately conservative — ТЗ §3.6 asks for arithmetic and wording suited to
#: 7-11 year olds, and a recommender optimising for engagement would happily
#: push past that.
DIFFICULTY_LADDER: dict[int, int] = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3}
MAX_DIFFICULTY = 3


class Segment(StrEnum):
    PLANNER = "planner"
    SPENDER = "spender"
    SAVER = "saver"
    EXPLORER = "explorer"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Hint:
    hint_id: str
    text: str
    next_step: str
    source: str  # "model" | "rule"


#: Hint catalogue. Each entry states what happened and what to do next — never a
#: verdict on the child. Texts are the child-facing strings, in Russian.
HINTS: dict[str, Hint] = {
    "essentials_first": Hint(
        "essentials_first",
        "Питомец остался голодным: обязательное не закрыто.",
        "В следующем плане поставь еду и уход первыми — так на желаемое тоже останется.",
        "rule",
    ),
    "plan_overspent": Hint(
        "plan_overspent",
        "Ты потратил на желаемое больше, чем планировал.",
        "Попробуй перенести одну необязательную покупку на следующий период.",
        "rule",
    ),
    "start_saving": Hint(
        "start_saving",
        "В этот раз в копилку ничего не попало.",
        "Отложи хотя бы 10 монет — цель сразу станет ближе.",
        "rule",
    ),
    "saving_but_hungry": Hint(
        "saving_but_hungry",
        "Копилка растёт, но питомцу не хватило еды.",
        "Сначала закрой обязательное, а в копилку отложи то, что осталось.",
        "rule",
    ),
    "keep_going": Hint(
        "keep_going",
        "План и факт почти совпали, и ты отложил часть монет.",
        "Так держать — попробуй в следующем периоде отложить чуть больше.",
        "rule",
    ),
    "steady_progress": Hint(
        "steady_progress",
        "Ты уверенно идёшь к цели.",
        "Посмотри, сколько периодов осталось до цели — совсем немного.",
        "rule",
    ),
    "try_cheaper": Hint(
        "try_cheaper",
        "Монет не хватило на покупку.",
        "Можно выбрать вариант подешевле или подождать следующий период — это не ошибка.",
        "rule",
    ),
    "explore_steady": Hint(
        "explore_steady",
        "Решения пока получаются очень разными.",
        "Попробуй составить план и придерживаться его весь период — так проще увидеть результат.",
        "rule",
    ),
}


@dataclass(frozen=True, slots=True)
class PeriodSnapshot:
    """The minimum the app must send to get a hint. No personal data, by design."""

    essential_coverage: float
    plan_adherence: float
    savings_rate: float
    rejected_purchases: int
    periods_completed: int


def rule_based_hint(snapshot: PeriodSnapshot) -> Hint:
    """Pick a hint from the snapshot alone.

    Ordering matters and encodes the pedagogy: an uncovered essential is always
    the most important thing to say, whatever else happened. Only once needs are
    met does the advice move on to plan discipline, then to saving.
    """
    if snapshot.essential_coverage < 0.85:
        if snapshot.savings_rate > 0.25:
            return HINTS["saving_but_hungry"]
        return HINTS["essentials_first"]
    if snapshot.rejected_purchases > 0:
        return HINTS["try_cheaper"]
    if snapshot.plan_adherence < 0.60:
        return HINTS["plan_overspent"]
    if snapshot.savings_rate <= 0.0:
        return HINTS["start_saving"]
    if snapshot.plan_adherence >= 0.80 and snapshot.savings_rate > 0.15:
        return HINTS["steady_progress"]
    return HINTS["keep_going"]


#: Which hint suits each predicted segment, *when the rules leave a choice*.
#: The model can refine the wording; it can never override the rules above.
SEGMENT_HINT: dict[Segment, str] = {
    Segment.SPENDER: "plan_overspent",
    Segment.SAVER: "saving_but_hungry",
    Segment.EXPLORER: "explore_steady",
    Segment.PLANNER: "steady_progress",
}


def hint_for(snapshot: PeriodSnapshot, segment: Segment = Segment.UNKNOWN) -> Hint:
    """Combine rules and model output, with the rules holding veto power.

    The model is consulted only for the «everything is fine» branch, where the
    rule has no strong opinion and the segment genuinely improves the wording.
    Any branch that reflects a concrete problem — uncovered essentials, a
    blocked purchase, an overspent plan — is decided by the rule alone.
    """
    rule_hint = rule_based_hint(snapshot)
    ambiguous = rule_hint.hint_id in {"keep_going", "steady_progress"}
    if not ambiguous or segment is Segment.UNKNOWN:
        return rule_hint

    candidate_id = SEGMENT_HINT.get(segment)
    if candidate_id is None or candidate_id not in HINTS:
        return rule_hint
    candidate = HINTS[candidate_id]
    return Hint(candidate.hint_id, candidate.text, candidate.next_step, source="model")


def max_difficulty_for(periods_completed: int) -> int:
    """Highest difficulty a child at this stage may be offered."""
    if periods_completed in DIFFICULTY_LADDER:
        return DIFFICULTY_LADDER[periods_completed]
    return MAX_DIFFICULTY


def recommend_quests(
    *,
    completed_quest_ids: set[str],
    topic_scores: dict[QuestTopic, float],
    periods_completed: int,
    model_scores: dict[str, float] | None = None,
    limit: int = 3,
    content: ContentPack | None = None,
) -> list[Quest]:
    """Choose the next quests.

    The rule, in order:

    1. Drop anything above the age-appropriate difficulty ceiling.
    2. Prefer quests from the weakest topic — the competency the child has
       practised least or done worst at. This is the educational objective, and
       it is not negotiable by a score.
    3. Prefer quests not yet completed, so content breadth comes before repetition.
    4. Only then, break ties by the model's predicted score.

    With ``model_scores=None`` the result is still complete and sensible — which
    is exactly what the app falls back to when the model fails to load.
    """
    pack = content or get_content()
    ceiling = max_difficulty_for(periods_completed)

    eligible = [q for q in pack.quests if q.difficulty <= ceiling]
    if not eligible:  # a brand-new profile: offer the gentlest quests available
        eligible = [
            q for q in pack.quests if q.difficulty == min(x.difficulty for x in pack.quests)
        ]

    # Topics the child has never touched score as 0.0 — the weakest possible —
    # which guarantees all three mandatory topics surface (ТЗ §2.5.8).
    def topic_weakness(quest: Quest) -> float:
        return topic_scores.get(quest.topic, 0.0)

    def sort_key(quest: Quest) -> tuple[float, int, float]:
        return (
            topic_weakness(quest),  # weakest topic first
            1 if quest.id in completed_quest_ids else 0,  # unseen first
            -(model_scores or {}).get(quest.id, 0.0),  # then model preference
        )

    ranked = sorted(eligible, key=sort_key)

    # Guarantee topic coverage in the returned slate: take the best quest from
    # each of the weakest topics before filling remaining slots.
    chosen: list[Quest] = []
    seen_topics: set[QuestTopic] = set()
    for quest in ranked:
        if quest.topic not in seen_topics:
            chosen.append(quest)
            seen_topics.add(quest.topic)
        if len(chosen) == limit:
            break
    for quest in ranked:
        if len(chosen) == limit:
            break
        if quest not in chosen:
            chosen.append(quest)
    return chosen[:limit]
