"""Event contracts — the single source of truth for the whole platform.

Everything downstream (generator, Kafka schemas, bronze tables, dbt sources,
feature definitions, the serving API) is derived from the models declared here.
Changing an event therefore means changing exactly one file, and the contract
tests in ``tests/unit/test_events.py`` fail loudly if a change is not backwards
compatible.

Privacy by construction
-----------------------
The customer's specification forbids collecting personal data of the child or
the adult (ТЗ §3.5). Three mechanisms enforce that here rather than leaving it
to reviewer discipline:

1. **No free text.** No event carries a user-authored string. The child's game
   name and the pet's name never leave the device; only the *pet appearance
   codes* (species/colour/accessory) are transmitted.
2. **Pseudonymous, resettable id.** ``profile_pseudo_id`` is a random UUIDv4
   minted on the device and destroyed when the adult resets the profile. It is
   not derived from any hardware identifier, account or phone number.
3. **A deny-list validator.** :func:`assert_no_personal_data` rejects any payload
   whose keys look like personal data. It runs in the generator, in the
   ingestion path and in CI, so a careless future event cannot slip through.

Telemetry is additionally **opt-in**: the device emits nothing until an adult
enables it in the protected section, and the mandatory game loop is fully
functional with telemetry disabled (ТЗ §3.1.5, §2.7).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Privacy guard
# ---------------------------------------------------------------------------

#: Whole words that must never appear as a token of a field name. Matching is
#: token-based (fields are split on non-alphanumerics) rather than by substring:
#: a plain substring rule flags `cumu-lat-ive` and `vo-lat-ility` for containing
#: "lat", and a guard that cries wolf gets switched off, which is the real risk.
FORBIDDEN_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "name",
        "surname",
        "patronymic",
        "fio",
        "email",
        "mail",
        "phone",
        "msisdn",
        "tel",
        "birth",
        "birthday",
        "birthdate",
        "dob",
        "age",
        "address",
        "street",
        "city",
        "zip",
        "postcode",
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "geo",
        "gps",
        "imei",
        "idfa",
        "gaid",
        "macaddress",
        "ip",
        "contact",
        "passport",
        "snils",
        "inn",
        "ssn",
        "card",
        "pan",
        "iban",
        "cvv",
        "account",
    }
)

#: Substrings that are unambiguous enough to match anywhere in a field name.
FORBIDDEN_NAME_SUBSTRINGS: tuple[str, ...] = (
    "android_id",
    "advertising_id",
    "device_id",
    "user_id",
    "full_name",
)

#: Fields that legitimately contain a forbidden token.
ALLOWED_KEY_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "event_name",  # the name of the event type, not of a person
        "model_name",  # the name of an ML model
        "item_name",  # a catalogue label, never user-authored
    }
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def personal_data_reason(field_name: str) -> str | None:
    """Return the rule a field name violates, or ``None`` when it is safe."""
    if field_name in ALLOWED_KEY_EXCEPTIONS:
        return None
    lowered = field_name.lower()
    for substring in FORBIDDEN_NAME_SUBSTRINGS:
        if substring in lowered:
            return f"substring {substring!r}"
    tokens = {token for token in _TOKEN_SPLIT.split(lowered) if token}
    forbidden = tokens & FORBIDDEN_NAME_TOKENS
    if forbidden:
        return f"token {sorted(forbidden)[0]!r}"
    return None


class PersonalDataError(ValueError):
    """Raised when an event payload looks like it carries personal data."""


def assert_no_personal_data(payload: dict[str, Any], *, path: str = "") -> None:
    """Recursively reject payload keys that resemble personal data.

    Raises:
        PersonalDataError: on the first suspicious key, naming its full path so
            the offending field is immediately obvious in CI output.
    """
    for key, value in payload.items():
        full = f"{path}.{key}" if path else key
        reason = personal_data_reason(key)
        if reason is not None:
            raise PersonalDataError(
                f"field {full!r} matches forbidden {reason}; "
                "telemetry must not carry personal data (ТЗ §3.5)"
            )
        if isinstance(value, dict):
            assert_no_personal_data(value, path=full)


# ---------------------------------------------------------------------------
# Enumerations — closed vocabularies keep the warehouse joinable and the
# contract auditable. A value not listed here cannot enter the lake.
# ---------------------------------------------------------------------------


class EventName(StrEnum):
    APP_OPENED = "app_opened"
    PROFILE_CREATED = "profile_created"
    PET_CUSTOMISED = "pet_customised"
    INCOME_GRANTED = "income_granted"
    BUDGET_PLAN_SUBMITTED = "budget_plan_submitted"
    PURCHASE_MADE = "purchase_made"
    PURCHASE_REJECTED = "purchase_rejected"
    SAVINGS_DEPOSITED = "savings_deposited"
    SAVINGS_WITHDRAWN = "savings_withdrawn"
    GOAL_SELECTED = "goal_selected"
    GOAL_REACHED = "goal_reached"
    QUEST_STARTED = "quest_started"
    QUEST_COMPLETED = "quest_completed"
    PERIOD_CLOSED = "period_closed"
    PET_STATE_CHANGED = "pet_state_changed"
    PET_STAGE_CHANGED = "pet_stage_changed"
    HINT_SHOWN = "hint_shown"
    TELEMETRY_CONSENT_CHANGED = "telemetry_consent_changed"


class ExpenseCategory(StrEnum):
    """ТЗ §2.5.5 — the two mandatory expense directions, plus savings."""

    ESSENTIAL = "essential"  # обязательные расходы
    OPTIONAL = "optional"  # необязательные расходы
    SAVINGS = "savings"  # накопления


class IncomeSource(StrEnum):
    """ТЗ §2.5.4 — every credit states its source and amount."""

    DAILY_LOGIN = "daily_login"
    QUEST_REWARD = "quest_reward"
    PERIOD_ALLOWANCE = "period_allowance"
    ADULT_BONUS = "adult_bonus"


class QuestTopic(StrEnum):
    """ТЗ §2.5.8 — at least three topics are mandatory."""

    BUDGETING = "budgeting"  # планирование бюджета
    SAVING = "saving"  # формирование сбережений
    PAYMENTS = "payments"  # платежи и покупки


class QuestOutcome(StrEnum):
    OPTIMAL = "optimal"
    SUBOPTIMAL = "suboptimal"
    POOR = "poor"


class PetStage(StrEnum):
    """ТЗ §2.6 — at least three growth stages."""

    HATCHLING = "hatchling"
    CUB = "cub"
    COMPANION = "companion"
    GUIDE = "guide"


class PetStateKind(StrEnum):
    MOOD = "mood"
    SATIETY = "satiety"
    ENERGY = "energy"
    TIDINESS = "tidiness"


class PetSpecies(StrEnum):
    FOX = "fox"
    CAT = "cat"
    OWL = "owl"


class PetColour(StrEnum):
    AMBER = "amber"
    MINT = "mint"
    LILAC = "lilac"


class PetAccessory(StrEnum):
    NONE = "none"
    SCARF = "scarf"
    CAP = "cap"


class RejectionReason(StrEnum):
    INSUFFICIENT_BALANCE = "insufficient_balance"
    WOULD_BREAK_ESSENTIALS = "would_break_essentials"
    OVER_PLAN_LIMIT = "over_plan_limit"


#: ТЗ §2.6 requires at least 9 visually distinct pet combinations.
PET_COMBINATION_COUNT = len(PetSpecies) * len(PetColour) * len(PetAccessory)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

Coins = Annotated[int, Field(ge=0, le=1_000_000, description="In-game currency, integer units")]
"""In-game currency. Integer by design: children aged 7-11 work with whole
numbers, and integers remove every rounding dispute from the economy."""


class EventEnvelope(BaseModel):
    """Common header shared by every telemetry event."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_name: EventName
    schema_version: int = SCHEMA_VERSION

    #: Device clock, UTC. May be skewed or even move backwards — silver layer
    #: repairs ordering using ``ingested_at`` as the tie-breaker.
    occurred_at: datetime

    #: Set by the ingestion tier, never by the device.
    ingested_at: datetime | None = None

    #: Random UUIDv4 minted on device, destroyed on profile reset. Not derived
    #: from hardware, account or phone number.
    profile_pseudo_id: uuid.UUID
    session_id: uuid.UUID

    #: Ordinal of the game period this event belongs to (ТЗ §2.5.5).
    period_no: int = Field(ge=0, le=10_000)

    #: Device context. Optional, and the reason is worth stating: these two
    #: fields describe the handset, and only the app can know them. An event
    #: relayed by the backend — or backfilled out of its database — genuinely
    #: has no device behind it, and filling in a plausible `33` would put a
    #: fabricated value into a typed column that analysis later trusts.
    #:
    #: Absent therefore means «did not come from a device», which is a fact
    #: worth keeping. `quality` flags it if the share of such events grows,
    #: so this cannot quietly become the norm.
    app_version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    android_api_level: int | None = Field(default=None, ge=26, le=40)

    #: True when the event originates from the expert demo mode (ТЗ §2.5.13).
    #: Demo traffic is kept out of every analytical mart.
    demo_mode: bool = False

    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _payload_carries_no_personal_data(self) -> EventEnvelope:
        assert_no_personal_data(self.payload)
        return self

    def partition_date(self) -> str:
        """Hive-style partition key for the bronze layer."""
        return self.occurred_at.date().isoformat()


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppOpenedPayload(_Payload):
    cold_start: bool
    #: ТЗ §3.4 — cold start to the main screen must stay under 5 000 ms.
    startup_latency_ms: int = Field(ge=0, le=120_000)


class ProfileCreatedPayload(_Payload):
    """No game name, no pet name — only the closed-vocabulary appearance codes."""

    pet_species: PetSpecies
    pet_colour: PetColour
    pet_accessory: PetAccessory
    onboarding_seconds: int = Field(ge=0, le=3_600)


class PetCustomisedPayload(_Payload):
    pet_species: PetSpecies
    pet_colour: PetColour
    pet_accessory: PetAccessory


class IncomeGrantedPayload(_Payload):
    """ТЗ §2.5.4 — the balance never changes without a stated source."""

    source: IncomeSource
    amount: Coins
    balance_after: Coins


class BudgetPlanSubmittedPayload(_Payload):
    """ТЗ §2.5.5 — the plan splits the available sum across ≥3 directions."""

    available_total: Coins
    planned_essential: Coins
    planned_optional: Coins
    planned_savings: Coins
    #: How many times the child edited the plan before confirming.
    revisions_count: int = Field(ge=0, le=100)
    seconds_spent: int = Field(ge=0, le=7_200)

    @model_validator(mode="after")
    def _plan_fits_budget(self) -> BudgetPlanSubmittedPayload:
        allocated = self.planned_essential + self.planned_optional + self.planned_savings
        if allocated > self.available_total:
            raise ValueError(
                f"plan allocates {allocated} of {self.available_total} available; "
                "the app must not allow over-allocation (ТЗ §2.5.5)"
            )
        return self

    @property
    def unallocated(self) -> int:
        return self.available_total - (
            self.planned_essential + self.planned_optional + self.planned_savings
        )


class PetEffect(_Payload):
    """Declared effect of a purchase on the pet, shown *before* confirming."""

    state: PetStateKind
    delta: int = Field(ge=-50, le=50)


class PurchaseMadePayload(_Payload):
    item_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    item_category: ExpenseCategory
    price: Coins
    balance_before: Coins
    balance_after: Coins
    effects: list[PetEffect] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _balance_is_consistent(self) -> PurchaseMadePayload:
        if self.balance_before - self.price != self.balance_after:
            raise ValueError(
                f"balance_before({self.balance_before}) - price({self.price}) "
                f"!= balance_after({self.balance_after})"
            )
        if self.item_category is ExpenseCategory.SAVINGS:
            raise ValueError("savings are not a purchase; use savings_deposited")
        return self


class PurchaseRejectedPayload(_Payload):
    """ТЗ §2.5.6 — a negative balance is impossible; the app explains instead."""

    item_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    item_category: ExpenseCategory
    price: Coins
    balance: Coins
    reason: RejectionReason

    @property
    def shortfall(self) -> int:
        return max(0, self.price - self.balance)


class SavingsDepositedPayload(_Payload):
    goal_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    amount: Coins
    savings_after: Coins
    balance_after: Coins


class SavingsWithdrawnPayload(_Payload):
    """ТЗ §2.5.7 — withdrawal requires a separate explicit confirmation, and the
    consequence is shown before it happens."""

    goal_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    amount: Coins
    savings_after: Coins
    balance_after: Coins
    confirmed: Literal[True]
    #: Projected periods-to-goal shown to the child before and after.
    eta_periods_before: int | None = Field(default=None, ge=0, le=999)
    eta_periods_after: int | None = Field(default=None, ge=0, le=999)


class GoalSelectedPayload(_Payload):
    goal_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    goal_cost: Coins
    savings_at_selection: Coins


class GoalReachedPayload(_Payload):
    goal_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    goal_cost: Coins
    periods_taken: int = Field(ge=1, le=999)


class QuestStartedPayload(_Payload):
    quest_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    topic: QuestTopic
    difficulty: int = Field(ge=1, le=3)
    #: Populated when the quest was chosen by the recommender (ТЗ §3.2 asks us
    #: to state where ML influenced the product).
    recommended_by_model: str | None = None


class QuestCompletedPayload(_Payload):
    quest_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    topic: QuestTopic
    difficulty: int = Field(ge=1, le=3)
    outcome: QuestOutcome
    choice_id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    attempts: int = Field(ge=1, le=20)
    seconds_spent: int = Field(ge=0, le=7_200)
    reward: Coins
    #: ТЗ §2.5.8 — an explanation is shown regardless of correctness.
    explanation_shown: Literal[True] = True


class PeriodClosedPayload(_Payload):
    """Fact of the period, compared against the plan (ТЗ §2.5.5, §2.5.10)."""

    closed_period_no: int = Field(ge=0, le=10_000)
    available_total: Coins
    planned_essential: Coins
    planned_optional: Coins
    planned_savings: Coins
    actual_essential: Coins
    actual_optional: Coins
    actual_savings: Coins
    #: Share of mandatory needs actually covered, 0.0-1.0.
    essential_coverage: float = Field(ge=0.0, le=1.0)
    leftover: Coins

    @property
    def plan_adherence(self) -> float:
        """1.0 when fact matches plan exactly; decays with total deviation.

        Deliberately a plain, explainable formula rather than a learned score —
        this number is shown to the child, and ТЗ §2.2 requires that every
        change answers «что изменилось и почему».
        """
        planned = self.planned_essential + self.planned_optional + self.planned_savings
        if planned == 0:
            return 0.0
        deviation = (
            abs(self.actual_essential - self.planned_essential)
            + abs(self.actual_optional - self.planned_optional)
            + abs(self.actual_savings - self.planned_savings)
        )
        return max(0.0, 1.0 - deviation / planned)


class PetStateChangedPayload(_Payload):
    state: PetStateKind
    value_before: int = Field(ge=0, le=100)
    value_after: int = Field(ge=0, le=100)
    #: Machine-readable cause so the UI can render a localised explanation
    #: without the reason text ever entering telemetry.
    reason_code: str = Field(pattern=r"^[a-z0-9_]{3,60}$")


class PetStageChangedPayload(_Payload):
    stage_before: PetStage
    stage_after: PetStage
    reason_code: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    periods_considered: int = Field(ge=1, le=100)


class HintShownPayload(_Payload):
    """A hint surfaced to the child, possibly chosen by a model.

    The model may only *choose which explanation to show*. It can never change
    the balance, block a purchase or alter the pet — that logic is deterministic
    and lives on device. See ``docs/ml-cards/`` for the guardrails.
    """

    hint_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    trigger: str = Field(pattern=r"^[a-z0-9_]{3,40}$")

    #: Which advisor cohort this device is in, assigned once per profile.
    #:
    #: Distinct from whether a model actually chose this particular hint: the
    #: model may only act where the rules are indifferent, so a device in the
    #: `model` cohort still shows rule hints most of the time. Recording the
    #: cohort separately is what makes an unbiased comparison possible — see
    #: mart_model_performance for why comparing by `model_name` instead gives
    #: the wrong answer.
    advisor_arm: Literal["rule", "model"] = "rule"

    model_name: str | None = None
    model_version: str | None = None
    #: Predicted behaviour segment that motivated this hint, when applicable.
    predicted_segment: str | None = None
    inference_latency_ms: int | None = Field(default=None, ge=0, le=10_000)


class TelemetryConsentChangedPayload(_Payload):
    """Adult-controlled opt-in switch (ТЗ §3.5). Default is *off*."""

    granted: bool
    #: Which protected-section barrier was passed (ТЗ §2.5.12).
    barrier: Literal["long_press", "arithmetic"]


#: Maps an event name to the model that validates its payload.
PAYLOAD_MODELS: dict[EventName, type[_Payload]] = {
    EventName.APP_OPENED: AppOpenedPayload,
    EventName.PROFILE_CREATED: ProfileCreatedPayload,
    EventName.PET_CUSTOMISED: PetCustomisedPayload,
    EventName.INCOME_GRANTED: IncomeGrantedPayload,
    EventName.BUDGET_PLAN_SUBMITTED: BudgetPlanSubmittedPayload,
    EventName.PURCHASE_MADE: PurchaseMadePayload,
    EventName.PURCHASE_REJECTED: PurchaseRejectedPayload,
    EventName.SAVINGS_DEPOSITED: SavingsDepositedPayload,
    EventName.SAVINGS_WITHDRAWN: SavingsWithdrawnPayload,
    EventName.GOAL_SELECTED: GoalSelectedPayload,
    EventName.GOAL_REACHED: GoalReachedPayload,
    EventName.QUEST_STARTED: QuestStartedPayload,
    EventName.QUEST_COMPLETED: QuestCompletedPayload,
    EventName.PERIOD_CLOSED: PeriodClosedPayload,
    EventName.PET_STATE_CHANGED: PetStateChangedPayload,
    EventName.PET_STAGE_CHANGED: PetStageChangedPayload,
    EventName.HINT_SHOWN: HintShownPayload,
    EventName.TELEMETRY_CONSENT_CHANGED: TelemetryConsentChangedPayload,
}


def validate_event(envelope: EventEnvelope) -> _Payload:
    """Validate an envelope's payload against the model for its event name.

    This is the gate between bronze and silver: anything that fails here is
    routed to the dead-letter topic rather than silently dropped.
    """
    model = PAYLOAD_MODELS.get(envelope.event_name)
    if model is None:
        raise ValueError(f"no payload contract registered for {envelope.event_name!r}")
    return model.model_validate(envelope.payload)


_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def build_event(
    *,
    event_name: EventName,
    payload: _Payload,
    profile_pseudo_id: uuid.UUID,
    session_id: uuid.UUID,
    period_no: int,
    occurred_at: datetime,
    app_version: str | None = "0.1.0",
    android_api_level: int | None = 33,
    demo_mode: bool = False,
    ingested_at: datetime | None = None,
) -> EventEnvelope:
    """Construct a fully validated envelope from a typed payload.

    ``ingested_at`` is normally left unset — the ingestion tier stamps it. The
    simulator passes it explicitly because it produces a historical backfill,
    where the delivery delay is part of what is being modelled.
    """
    if app_version is not None and not _SEMVER.match(app_version):
        raise ValueError(f"app_version must be semver, got {app_version!r}")
    return EventEnvelope(
        event_name=event_name,
        payload=payload.model_dump(mode="json"),
        profile_pseudo_id=profile_pseudo_id,
        session_id=session_id,
        period_no=period_no,
        occurred_at=occurred_at,
        ingested_at=ingested_at,
        app_version=app_version,
        android_api_level=android_api_level,
        demo_mode=demo_mode,
    )
