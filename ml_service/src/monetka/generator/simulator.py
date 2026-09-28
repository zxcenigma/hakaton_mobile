"""Synthetic telemetry simulator.

Why synthetic data at all
-------------------------
The customer's specification forbids collecting personal data from children
(ТЗ §3.5) and the mandatory game loop runs entirely offline (ТЗ §3.1.5). A real
event stream from real children is therefore both unavailable and undesirable.
Everything this platform is built and tested on is generated here.

That is not a workaround — it is the honest design. The simulator encodes the
*same* deterministic economy the Android app implements, so the pipeline,
feature definitions and models are exercised against data with exactly the
shape production data would have, while no child is ever observed.

What is modelled
----------------
Four behavioural archetypes, each a plausible way a 7-11 year old plays:

``planner``  plans carefully, follows the plan, saves every period.
``spender``  buys wants first, discovers too late that needs are unaffordable.
``saver``    over-saves, occasionally starving the pet of essentials.
``explorer`` erratic early on, high variance, no stable strategy yet.

Crucially, every archetype **learns**: a per-player ``learning_rate`` pulls
behaviour towards the planner strategy as periods accumulate. This is what makes
the dataset interesting — the educational effect is a real, measurable signal in
the data rather than a flat distribution, and it gives the drift monitors
something genuine to detect.

The archetype label never enters the event stream. It is recorded separately in
:attr:`Simulator.labels` and persisted to its own dataset, because in production
no such label exists — a model that quietly learned from a field unavailable at
inference time would be worthless. Training joins the labels explicitly, which
keeps that dependency visible.
"""

from __future__ import annotations

import math
import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported lazily at runtime to keep the generator standalone
    from monetka.serving.recommender import Segment

from monetka.common.content import CatalogItem, ContentPack, Goal, Quest, get_content
from monetka.common.events import (
    AppOpenedPayload,
    BudgetPlanSubmittedPayload,
    EventEnvelope,
    EventName,
    ExpenseCategory,
    GoalReachedPayload,
    GoalSelectedPayload,
    HintShownPayload,
    IncomeGrantedPayload,
    IncomeSource,
    PeriodClosedPayload,
    PetAccessory,
    PetColour,
    PetEffect,
    PetSpecies,
    PetStageChangedPayload,
    PetStateChangedPayload,
    PetStateKind,
    ProfileCreatedPayload,
    PurchaseMadePayload,
    PurchaseRejectedPayload,
    QuestCompletedPayload,
    QuestOutcome,
    QuestStartedPayload,
    RejectionReason,
    SavingsDepositedPayload,
    SavingsWithdrawnPayload,
    build_event,
)

#: Base allowance per period. Sized from the content pack so that covering every
#: mandatory need is always affordable — a child must never be trapped by the
#: economy itself (ТЗ §2.2 «безопасная ошибка»).
ALLOWANCE_HEADROOM = 1.45

#: Share of simulated players whose advisor is «model-personalised». The rest see
#: the rule-based hint. This is what gives `mart_hint_effectiveness` two arms to
#: compare, the same way a real rollout would hold back a control group.
MODEL_ARM_SHARE = 0.5

#: How strongly a shown hint nudges the next period's behaviour.
#:
#: This is an **assumption of the simulation**, not a finding about children. It
#: exists so the measurement pipeline has a signal to measure and can be shown to
#: recover it; the effect size is deliberately small, because a large one would
#: make the analytics look impressive for reasons that are entirely circular.
#: Any claim about real pedagogical effect requires a study with consent
#: (ТЗ §8.4) — see docs/ml-cards/hint_effectiveness.md.
HINT_RESPONSE = 0.06

#: Extra responsiveness attributed to a hint the model personalised. Also an
#: assumption; it is what the monitoring is asked to detect.
HINT_RESPONSE_MODEL_BONUS = 0.03


class Archetype(StrEnum):
    PLANNER = "planner"
    SPENDER = "spender"
    SAVER = "saver"
    EXPLORER = "explorer"


@dataclass(frozen=True, slots=True)
class ArchetypeProfile:
    """Behavioural parameters. All shares are of the period's available coins."""

    essential_share: float
    optional_share: float
    savings_share: float
    #: Probability of deviating from the submitted plan when buying.
    impulse_probability: float
    #: Probability of attempting a purchase that cannot be afforded.
    overreach_probability: float
    #: Probability of raiding the goal savings.
    withdraw_probability: float
    #: Probability of picking the pedagogically optimal quest choice.
    optimal_choice_probability: float


ARCHETYPES: dict[Archetype, ArchetypeProfile] = {
    Archetype.PLANNER: ArchetypeProfile(0.52, 0.20, 0.28, 0.10, 0.04, 0.03, 0.78),
    Archetype.SPENDER: ArchetypeProfile(0.38, 0.55, 0.07, 0.55, 0.30, 0.22, 0.38),
    Archetype.SAVER: ArchetypeProfile(0.40, 0.08, 0.52, 0.12, 0.08, 0.02, 0.62),
    Archetype.EXPLORER: ArchetypeProfile(0.45, 0.33, 0.22, 0.40, 0.22, 0.14, 0.48),
}

#: Population mix. Roughly mirrors what teachers report about this age group:
#: a large undecided middle, with committed planners and spenders at the tails.
ARCHETYPE_WEIGHTS: dict[Archetype, float] = {
    Archetype.PLANNER: 0.22,
    Archetype.SPENDER: 0.28,
    Archetype.SAVER: 0.18,
    Archetype.EXPLORER: 0.32,
}


@dataclass(slots=True)
class PetState:
    """Pet condition, clamped to the floor so errors stay recoverable."""

    values: dict[PetStateKind, int]
    floor: int
    ceiling: int

    def apply(self, kind: PetStateKind, delta: int) -> tuple[int, int]:
        before = self.values[kind]
        after = max(self.floor, min(self.ceiling, before + delta))
        self.values[kind] = after
        return before, after


@dataclass(slots=True)
class PlayerState:
    """Everything the simulator tracks for one virtual player."""

    profile_id: uuid.UUID
    archetype: Archetype
    learning_rate: float
    balance: int = 0
    savings: int = 0
    goal: Goal | None = None
    goals_reached: int = 0
    stage_index: int = 0
    pet: PetState | None = None
    completed_quests: set[str] = field(default_factory=set)
    # Rolling history used to decide the growth stage.
    essential_coverage_history: list[float] = field(default_factory=list)
    plan_adherence_history: list[float] = field(default_factory=list)
    periods_with_savings: int = 0

    #: Which advisor arm this player is in: True = the model personalises the
    #: hint wording, False = rules only. Fixed per player, like a real holdout.
    model_arm: bool = False
    #: Hint shown at the end of the previous period, and how strongly it nudges
    #: this period's behaviour. Consumed once, then cleared.
    pending_nudge: float = 0.0


class Simulator:
    """Generates a validated event stream for a cohort of virtual players."""

    def __init__(
        self,
        content: ContentPack | None = None,
        *,
        seed: int = 20260305,
        app_version: str = "0.1.0",
        model_version: str = "20260305T000000Z",
    ) -> None:
        self.content = content or get_content()
        self.rng = random.Random(seed)
        self.app_version = app_version
        #: Version stamped on hints the model personalised, so monitoring can
        #: attribute behaviour to a specific deployed model.
        self.model_version = model_version
        #: Ground truth for offline training: profile_pseudo_id -> archetype.
        #: Deliberately kept out of the event stream (see module docstring).
        self.labels: dict[str, str] = {}
        self._essentials = self.content.items_by_category(ExpenseCategory.ESSENTIAL)
        self._optionals = self.content.items_by_category(ExpenseCategory.OPTIONAL)
        self._base_allowance = max(60, int(self.content.essential_period_cost * ALLOWANCE_HEADROOM))

    # ------------------------------------------------------------- public --

    def simulate_cohort(
        self,
        n_players: int,
        n_periods: int,
        start_date: datetime,
    ) -> Iterator[EventEnvelope]:
        """Yield the full event stream for ``n_players`` over ``n_periods``."""
        for _ in range(n_players):
            # Players join on staggered days so the bronze layer gets a realistic
            # spread of partitions rather than one giant hot partition.
            joined = start_date + timedelta(days=self.rng.randint(0, 21))
            yield from self.simulate_player(n_periods, joined)

    def simulate_player(self, n_periods: int, joined_at: datetime) -> Iterator[EventEnvelope]:
        player = self._new_player()
        clock = joined_at

        yield from self._onboarding(player, clock)
        clock += timedelta(minutes=3)

        for period_no in range(1, n_periods + 1):
            events, clock = self._simulate_period(player, period_no, clock)
            yield from events
            # A period spans a few days of wall-clock time; the app itself never
            # requires waiting (demo mode replays them back to back, ТЗ §2.5.13).
            clock += timedelta(days=self.rng.randint(2, 4), hours=self.rng.randint(0, 10))

    # ------------------------------------------------------------ helpers --

    def _new_player(self) -> PlayerState:
        archetype = self.rng.choices(
            list(ARCHETYPE_WEIGHTS), weights=list(ARCHETYPE_WEIGHTS.values()), k=1
        )[0]
        rules = self.content.pet_rules
        profile_id = uuid.uuid4()
        self.labels[str(profile_id)] = archetype.value
        return PlayerState(
            profile_id=profile_id,
            archetype=archetype,
            model_arm=self.rng.random() < MODEL_ARM_SHARE,
            # Some children internalise the lesson quickly, some slowly.
            learning_rate=self.rng.betavariate(2.0, 5.0),
            pet=PetState(
                values=dict.fromkeys(PetStateKind, rules.initial_value),
                floor=rules.floor_value,
                ceiling=rules.ceiling_value,
            ),
        )

    def _effective_profile(self, player: PlayerState, period_no: int) -> ArchetypeProfile:
        """Blend the archetype towards the planner strategy as the child learns.

        ``progress`` saturates: most of the change happens over the first handful
        of periods, which matches how the game is actually played and keeps the
        drift signal realistic rather than linear.
        """
        base = ARCHETYPES[player.archetype]
        target = ARCHETYPES[Archetype.PLANNER]
        progress = 1.0 - math.exp(-player.learning_rate * (period_no - 1))

        # A hint shown at the end of the previous period nudges this one a little
        # further towards the planner strategy. Consumed once — a hint does not
        # keep working forever, which is the point of showing a new one.
        progress = min(1.0, progress + player.pending_nudge)
        player.pending_nudge = 0.0

        def blend(attr: str) -> float:
            return getattr(base, attr) + (getattr(target, attr) - getattr(base, attr)) * progress

        return ArchetypeProfile(
            essential_share=blend("essential_share"),
            optional_share=blend("optional_share"),
            savings_share=blend("savings_share"),
            impulse_probability=blend("impulse_probability"),
            overreach_probability=blend("overreach_probability"),
            withdraw_probability=blend("withdraw_probability"),
            optimal_choice_probability=blend("optimal_choice_probability"),
        )

    def _emit(
        self,
        player: PlayerState,
        session: uuid.UUID,
        period_no: int,
        name: EventName,
        payload: object,
        at: datetime,
    ) -> EventEnvelope:
        return build_event(
            event_name=name,
            payload=payload,  # type: ignore[arg-type]
            profile_pseudo_id=player.profile_id,
            session_id=session,
            period_no=period_no,
            occurred_at=at,
            ingested_at=at + self._delivery_delay(),
            app_version=self.app_version,
            android_api_level=self.rng.choice([26, 28, 29, 30, 31, 33, 34]),
        )

    def _delivery_delay(self) -> timedelta:
        """How long an event takes to reach the platform.

        The app is offline-first (ТЗ §3.1.5): events are buffered on device and
        flushed on the next connectivity. Most arrive within seconds, a tail
        arrives hours later, and a small fraction waits days because the tablet
        stayed offline. That tail is not noise to be smoothed away — it is what
        the late-arrival quality check and the Airflow watermark logic exist to
        handle, so the generator has to produce it.
        """
        roll = self.rng.random()
        if roll < 0.80:
            return timedelta(seconds=self.rng.randint(1, 90))
        if roll < 0.97:
            return timedelta(minutes=self.rng.randint(2, 600))
        return timedelta(hours=self.rng.randint(12, 200))

    # --------------------------------------------------------- onboarding --

    def _onboarding(self, player: PlayerState, clock: datetime) -> Iterator[EventEnvelope]:
        session = uuid.uuid4()
        yield self._emit(
            player,
            session,
            0,
            EventName.APP_OPENED,
            AppOpenedPayload(
                cold_start=True,
                # ТЗ §3.4 — under 5 000 ms to the main screen on the test device.
                startup_latency_ms=self.rng.randint(900, 3_400),
            ),
            clock,
        )
        yield self._emit(
            player,
            session,
            0,
            EventName.PROFILE_CREATED,
            ProfileCreatedPayload(
                pet_species=self.rng.choice(list(PetSpecies)),
                pet_colour=self.rng.choice(list(PetColour)),
                pet_accessory=self.rng.choice(list(PetAccessory)),
                onboarding_seconds=self.rng.randint(40, 300),
            ),
            clock + timedelta(seconds=30),
        )

        goal = self.rng.choice(self.content.goals)
        player.goal = goal
        yield self._emit(
            player,
            session,
            0,
            EventName.GOAL_SELECTED,
            GoalSelectedPayload(goal_id=goal.id, goal_cost=goal.cost, savings_at_selection=0),
            clock + timedelta(seconds=90),
        )

    # ------------------------------------------------------------- period --

    def _simulate_period(
        self, player: PlayerState, period_no: int, clock: datetime
    ) -> tuple[list[EventEnvelope], datetime]:
        session = uuid.uuid4()
        events: list[EventEnvelope] = []
        profile = self._effective_profile(player, period_no)
        rules = self.content.pet_rules
        assert player.pet is not None

        events.append(
            self._emit(
                player,
                session,
                period_no,
                EventName.APP_OPENED,
                AppOpenedPayload(cold_start=True, startup_latency_ms=self.rng.randint(700, 2_900)),
                clock,
            )
        )

        # ---- income (ТЗ §2.5.4: every credit names its source) -------------
        allowance = self._base_allowance + self.rng.randint(-8, 12)
        player.balance += allowance
        events.append(
            self._emit(
                player,
                session,
                period_no,
                EventName.INCOME_GRANTED,
                IncomeGrantedPayload(
                    source=IncomeSource.PERIOD_ALLOWANCE,
                    amount=allowance,
                    balance_after=player.balance,
                ),
                clock + timedelta(minutes=1),
            )
        )
        if self.rng.random() < 0.45:
            bonus = self.rng.choice([5, 8, 10])
            player.balance += bonus
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.INCOME_GRANTED,
                    IncomeGrantedPayload(
                        source=IncomeSource.DAILY_LOGIN,
                        amount=bonus,
                        balance_after=player.balance,
                    ),
                    clock + timedelta(minutes=2),
                )
            )

        # ---- plan (ТЗ §2.5.5) ---------------------------------------------
        available = player.balance
        planned_essential = int(available * profile.essential_share)
        planned_optional = int(available * profile.optional_share)
        planned_savings = int(available * profile.savings_share)
        # The app refuses over-allocation, so the simulator must too.
        overflow = (planned_essential + planned_optional + planned_savings) - available
        if overflow > 0:
            planned_optional = max(0, planned_optional - overflow)

        plan = BudgetPlanSubmittedPayload(
            available_total=available,
            planned_essential=planned_essential,
            planned_optional=planned_optional,
            planned_savings=planned_savings,
            revisions_count=self.rng.randint(0, 4),
            seconds_spent=self.rng.randint(20, 240),
        )
        events.append(
            self._emit(
                player,
                session,
                period_no,
                EventName.BUDGET_PLAN_SUBMITTED,
                plan,
                clock + timedelta(minutes=4),
            )
        )

        cursor = clock + timedelta(minutes=6)

        # ---- quests (ТЗ §2.5.8) -------------------------------------------
        quest_events, cursor, quest_income = self._play_quests(
            player, session, period_no, profile, cursor
        )
        events.extend(quest_events)

        # ---- purchases (ТЗ §2.5.6) ----------------------------------------
        purchase_events, cursor, spent = self._make_purchases(
            player, session, period_no, profile, plan, cursor
        )
        events.extend(purchase_events)

        # ---- savings (ТЗ §2.5.7) ------------------------------------------
        savings_events, cursor, deposited = self._move_savings(
            player, session, period_no, profile, plan, cursor
        )
        events.extend(savings_events)

        # ---- pet reaction & period close ----------------------------------
        essential_need = sum(i.price * i.period_need for i in self._essentials)
        coverage = (
            min(1.0, spent[ExpenseCategory.ESSENTIAL] / essential_need) if essential_need else 1.0
        )

        for kind, decay in rules.decay_per_period.items():
            before, after = player.pet.apply(kind, -decay)
            if before != after:
                events.append(
                    self._emit(
                        player,
                        session,
                        period_no,
                        EventName.PET_STATE_CHANGED,
                        PetStateChangedPayload(
                            state=kind,
                            value_before=before,
                            value_after=after,
                            reason_code="essentials_covered"
                            if coverage >= 0.85
                            else "essentials_missed",
                        ),
                        cursor,
                    )
                )
        cursor += timedelta(minutes=1)

        closed = PeriodClosedPayload(
            closed_period_no=period_no,
            available_total=available + quest_income,
            planned_essential=plan.planned_essential,
            planned_optional=plan.planned_optional,
            planned_savings=plan.planned_savings,
            actual_essential=spent[ExpenseCategory.ESSENTIAL],
            actual_optional=spent[ExpenseCategory.OPTIONAL],
            actual_savings=deposited,
            essential_coverage=round(coverage, 4),
            leftover=player.balance,
        )
        events.append(
            self._emit(player, session, period_no, EventName.PERIOD_CLOSED, closed, cursor)
        )

        player.essential_coverage_history.append(coverage)
        player.plan_adherence_history.append(closed.plan_adherence)
        if deposited > 0:
            player.periods_with_savings += 1

        # ---- growth stage (ТЗ §2.5.10) ------------------------------------
        stage_event = self._maybe_advance_stage(player, session, period_no, cursor)
        if stage_event is not None:
            events.append(stage_event)

        # ---- advisor (ТЗ §2.5.9) ------------------------------------------
        cursor += timedelta(seconds=15)
        events.append(
            self._show_hint(
                player,
                session,
                period_no,
                coverage=coverage,
                adherence=closed.plan_adherence,
                savings_rate=(deposited / available) if available else 0.0,
                rejections=sum(1 for e in events if e.event_name is EventName.PURCHASE_REJECTED),
                at=cursor,
            )
        )

        return events, cursor

    # -------------------------------------------------------------- advisor --

    def _predicted_segment(self, player: PlayerState, period_no: int) -> Segment:
        """What the deployed model would have predicted — right or wrong.

        Emphatically **not** the ground-truth archetype. Writing the true label
        into telemetry would leak it into the warehouse, and it would also be a
        lie about production: the model is ~89% accurate inside its validated
        horizon and degrades to ~55% beyond it, because archetypes converge as
        children learn.

        Reproducing that error rate here is what makes the monitoring marts
        meaningful — `mart_model_performance` can then show the degradation the
        way it would appear in production, instead of showing a model that is
        always right.
        """
        from monetka.ml.features import BEHAVIOUR_MAX_PERIOD
        from monetka.serving.recommender import Segment

        # Matches the measured decay: 0.89 at period 3, ~0.54 by period 12.
        accuracy = (
            0.89
            if period_no <= BEHAVIOUR_MAX_PERIOD
            else max(0.52, 0.89 - 0.06 * (period_no - BEHAVIOUR_MAX_PERIOD))
        )
        truth = Segment(player.archetype.value)
        if self.rng.random() < accuracy:
            return truth
        alternatives = [s for s in Segment if s is not Segment.UNKNOWN and s is not truth]
        return self.rng.choice(alternatives)

    def _show_hint(
        self,
        player: PlayerState,
        session: uuid.UUID,
        period_no: int,
        *,
        coverage: float,
        adherence: float,
        savings_rate: float,
        rejections: int,
        at: datetime,
    ) -> EventEnvelope:
        """Emit the hint the Советник showed at the close of the period.

        The hint is chosen by importing the *same* rule module the serving layer
        and the app use. That is deliberate: if the simulated app and the
        reference implementation could disagree about which hint a situation
        calls for, every downstream measurement of hint effectiveness would be
        measuring the disagreement rather than the hint.
        """
        from monetka.serving.recommender import PeriodSnapshot, Segment, hint_for

        snapshot = PeriodSnapshot(
            essential_coverage=coverage,
            plan_adherence=adherence,
            savings_rate=savings_rate,
            rejected_purchases=rejections,
            periods_completed=period_no,
        )

        # Players in the model arm get the segment-aware wording, but only where
        # the rules are indifferent — exactly the constraint the product enforces.
        segment = Segment.UNKNOWN
        if player.model_arm:
            segment = self._predicted_segment(player, period_no)
        hint = hint_for(snapshot, segment)

        nudge = HINT_RESPONSE
        if hint.source == "model":
            nudge += HINT_RESPONSE_MODEL_BONUS
        player.pending_nudge = nudge

        return self._emit(
            player,
            session,
            period_no,
            EventName.HINT_SHOWN,
            HintShownPayload(
                hint_id=hint.hint_id,
                trigger="period_closed",
                advisor_arm="model" if player.model_arm else "rule",
                model_name="behaviour_segment" if hint.source == "model" else None,
                model_version=self.model_version if hint.source == "model" else None,
                predicted_segment=segment.value if hint.source == "model" else None,
                inference_latency_ms=self.rng.randint(3, 34) if hint.source == "model" else None,
            ),
            at,
        )

    # -------------------------------------------------------------- quests --

    def _play_quests(
        self,
        player: PlayerState,
        session: uuid.UUID,
        period_no: int,
        profile: ArchetypeProfile,
        cursor: datetime,
    ) -> tuple[list[EventEnvelope], datetime, int]:
        events: list[EventEnvelope] = []
        earned = 0
        n_quests = self.rng.randint(1, 3)
        pool: list[Quest] = [q for q in self.content.quests if q.id not in player.completed_quests]
        if not pool:  # every quest done — replay for practice
            pool = list(self.content.quests)

        for quest in self.rng.sample(pool, k=min(n_quests, len(pool))):
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.QUEST_STARTED,
                    QuestStartedPayload(
                        quest_id=quest.id, topic=quest.topic, difficulty=quest.difficulty
                    ),
                    cursor,
                )
            )
            cursor += timedelta(seconds=self.rng.randint(15, 60))

            # Harder quests are harder to get right, whatever the archetype.
            p_optimal = profile.optimal_choice_probability * (1.0 - 0.12 * (quest.difficulty - 1))
            if self.rng.random() < p_optimal:
                choice = self.rng.choice(quest.optimal_choices)
            else:
                non_optimal = [c for c in quest.choices if c.outcome is not QuestOutcome.OPTIMAL]
                choice = self.rng.choice(non_optimal or quest.choices)

            player.balance += choice.reward
            earned += choice.reward
            player.completed_quests.add(quest.id)

            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.QUEST_COMPLETED,
                    QuestCompletedPayload(
                        quest_id=quest.id,
                        topic=quest.topic,
                        difficulty=quest.difficulty,
                        outcome=choice.outcome,
                        choice_id=choice.id,
                        attempts=1
                        if choice.outcome is QuestOutcome.OPTIMAL
                        else self.rng.randint(1, 3),
                        seconds_spent=self.rng.randint(20, 300),
                        reward=choice.reward,
                    ),
                    cursor,
                )
            )
            if choice.reward:
                events.append(
                    self._emit(
                        player,
                        session,
                        period_no,
                        EventName.INCOME_GRANTED,
                        IncomeGrantedPayload(
                            source=IncomeSource.QUEST_REWARD,
                            amount=choice.reward,
                            balance_after=player.balance,
                        ),
                        cursor + timedelta(seconds=2),
                    )
                )
            cursor += timedelta(minutes=self.rng.randint(1, 4))

        return events, cursor, earned

    # ----------------------------------------------------------- purchases --

    def _make_purchases(
        self,
        player: PlayerState,
        session: uuid.UUID,
        period_no: int,
        profile: ArchetypeProfile,
        plan: BudgetPlanSubmittedPayload,
        cursor: datetime,
    ) -> tuple[list[EventEnvelope], datetime, dict[ExpenseCategory, int]]:
        events: list[EventEnvelope] = []
        spent = {ExpenseCategory.ESSENTIAL: 0, ExpenseCategory.OPTIONAL: 0}

        # Spenders shop for wants first — that is precisely the mistake the game
        # is designed to surface.
        wants_first = self.rng.random() < profile.impulse_probability
        queue: list[CatalogItem] = []
        essentials = [i for i in self._essentials for _ in range(i.period_need)]
        optionals = self.rng.sample(self._optionals, k=self.rng.randint(1, 4))
        queue = [*optionals, *essentials] if wants_first else [*essentials, *optionals]

        # An occasional unexpected expense — a *planned* scenario, never a
        # punishment for a mistake (ТЗ §2).
        unexpected = [i for i in self._essentials if i.unexpected]
        if unexpected and self.rng.random() < 0.18:
            queue.insert(self.rng.randint(0, len(queue)), unexpected[0])

        for item in queue:
            if item.price > player.balance:
                events.append(
                    self._emit(
                        player,
                        session,
                        period_no,
                        EventName.PURCHASE_REJECTED,
                        PurchaseRejectedPayload(
                            item_id=item.id,
                            item_category=item.category,
                            price=item.price,
                            balance=player.balance,
                            reason=RejectionReason.INSUFFICIENT_BALANCE,
                        ),
                        cursor,
                    )
                )
                cursor += timedelta(seconds=self.rng.randint(5, 40))
                continue

            # Stick to the plan unless an impulse strikes.
            budget_left = (
                plan.planned_optional - spent[ExpenseCategory.OPTIONAL]
                if item.category is ExpenseCategory.OPTIONAL
                else plan.planned_essential - spent[ExpenseCategory.ESSENTIAL]
            )
            if item.price > budget_left and self.rng.random() > profile.impulse_probability:
                continue

            before = player.balance
            player.balance -= item.price
            spent[item.category] += item.price
            assert player.pet is not None
            for effect in item.effects:
                player.pet.apply(effect.state, effect.delta)

            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.PURCHASE_MADE,
                    PurchaseMadePayload(
                        item_id=item.id,
                        item_category=item.category,
                        price=item.price,
                        balance_before=before,
                        balance_after=player.balance,
                        effects=[PetEffect(state=e.state, delta=e.delta) for e in item.effects],
                    ),
                    cursor,
                )
            )
            cursor += timedelta(seconds=self.rng.randint(10, 90))

        # Deliberate over-reach: the child tries something unaffordable and the
        # app explains rather than blocks silently (ТЗ §2.5.6).
        if self.rng.random() < profile.overreach_probability:
            pricey = max(self._optionals, key=lambda i: i.price)
            if pricey.price > player.balance:
                events.append(
                    self._emit(
                        player,
                        session,
                        period_no,
                        EventName.PURCHASE_REJECTED,
                        PurchaseRejectedPayload(
                            item_id=pricey.id,
                            item_category=pricey.category,
                            price=pricey.price,
                            balance=player.balance,
                            reason=RejectionReason.INSUFFICIENT_BALANCE,
                        ),
                        cursor,
                    )
                )
                cursor += timedelta(seconds=20)

        return events, cursor, spent

    # ------------------------------------------------------------- savings --

    def _move_savings(
        self,
        player: PlayerState,
        session: uuid.UUID,
        period_no: int,
        profile: ArchetypeProfile,
        plan: BudgetPlanSubmittedPayload,
        cursor: datetime,
    ) -> tuple[list[EventEnvelope], datetime, int]:
        events: list[EventEnvelope] = []
        if player.goal is None:
            return events, cursor, 0

        deposit = min(player.balance, plan.planned_savings)
        deposited = 0
        if deposit > 0:
            player.balance -= deposit
            player.savings += deposit
            deposited = deposit
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.SAVINGS_DEPOSITED,
                    SavingsDepositedPayload(
                        goal_id=player.goal.id,
                        amount=deposit,
                        savings_after=player.savings,
                        balance_after=player.balance,
                    ),
                    cursor,
                )
            )
            cursor += timedelta(seconds=30)

        # Raiding the goal — allowed, but only after an explicit confirmation,
        # and the ETA change is shown beforehand (ТЗ §2.5.7).
        if player.savings > 0 and self.rng.random() < profile.withdraw_probability:
            amount = min(player.savings, self.rng.randint(5, 45))
            avg_deposit = max(1, player.savings // max(1, period_no))
            eta_before = math.ceil(max(0, player.goal.cost - player.savings) / avg_deposit)
            player.savings -= amount
            player.balance += amount
            eta_after = math.ceil(max(0, player.goal.cost - player.savings) / avg_deposit)
            deposited -= amount
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.SAVINGS_WITHDRAWN,
                    SavingsWithdrawnPayload(
                        goal_id=player.goal.id,
                        amount=amount,
                        savings_after=player.savings,
                        balance_after=player.balance,
                        confirmed=True,
                        eta_periods_before=min(999, eta_before),
                        eta_periods_after=min(999, eta_after),
                    ),
                    cursor,
                )
            )
            cursor += timedelta(seconds=40)

        # Goal reached — celebrate, then offer a new one.
        if player.savings >= player.goal.cost:
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.GOAL_REACHED,
                    GoalReachedPayload(
                        goal_id=player.goal.id,
                        goal_cost=player.goal.cost,
                        periods_taken=period_no,
                    ),
                    cursor,
                )
            )
            player.savings -= player.goal.cost
            player.goals_reached += 1
            next_goal = self.rng.choice(self.content.goals)
            player.goal = next_goal
            cursor += timedelta(seconds=20)
            events.append(
                self._emit(
                    player,
                    session,
                    period_no,
                    EventName.GOAL_SELECTED,
                    GoalSelectedPayload(
                        goal_id=next_goal.id,
                        goal_cost=next_goal.cost,
                        savings_at_selection=player.savings,
                    ),
                    cursor,
                )
            )
            cursor += timedelta(seconds=20)

        return events, cursor, max(0, deposited)

    # --------------------------------------------------------------- stage --

    def _maybe_advance_stage(
        self, player: PlayerState, session: uuid.UUID, period_no: int, cursor: datetime
    ) -> EventEnvelope | None:
        rules = self.content.pet_rules
        window = rules.evaluation_window_periods
        coverage = player.essential_coverage_history[-window:]
        adherence = player.plan_adherence_history[-window:]

        metrics = {
            "periods_completed": float(period_no),
            "avg_essential_coverage": sum(coverage) / len(coverage) if coverage else 0.0,
            "avg_plan_adherence": sum(adherence) / len(adherence) if adherence else 0.0,
            "periods_with_savings": float(player.periods_with_savings),
            "goals_reached": float(player.goals_reached),
        }
        target = rules.stage_for(metrics)
        target_index = rules.stage_order.index(target)

        # ТЗ §2 — the stage never regresses; progress already earned is kept.
        if target_index <= player.stage_index:
            return None

        before = rules.stage_order[player.stage_index]
        player.stage_index = target_index
        return self._emit(
            player,
            session,
            period_no,
            EventName.PET_STAGE_CHANGED,
            PetStageChangedPayload(
                stage_before=before,
                stage_after=target,
                reason_code="plan_followed"
                if metrics["avg_plan_adherence"] >= 0.6
                else "essentials_covered",
                periods_considered=len(coverage) or 1,
            ),
            cursor + timedelta(seconds=10),
        )
