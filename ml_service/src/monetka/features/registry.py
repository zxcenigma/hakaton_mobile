"""Feature registry.

Every feature the platform serves is declared here: what it means, where it is
computed, the range it may take, and which models consume it.

Why this rather than Feast
--------------------------
An earlier draft listed Feast in the dependencies. It was never wired up, and on
reflection it should not be: a feature store earns its keep when several teams
share features across online and offline paths with different freshness needs.
Here there is one consumer, the features are computed by one dbt model, and
inference happens **on the phone** — a store the device cannot reach solves
nothing. Carrying it would have been a dependency for the architecture diagram
rather than for the product.

What is genuinely needed is the part a feature store is actually valued for, and
it is small enough to own:

* a **single declaration** of each feature, so training and the device cannot
  disagree about what `savings_rate` means;
* a **point-in-time rule** per feature, so nobody silently introduces one that
  looks into the future;
* **range validation**, so a feature drifting out of its declared domain is
  caught rather than quietly scored;
* **ownership**, so a model cannot consume a feature that nobody declared.

The last point is enforced by a test: every name in a model's `feature_names`
must exist here, and every feature here must be produced by the mart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Window(StrEnum):
    """How far back a feature looks. The point-in-time contract."""

    #: Computed from the closing period only.
    CURRENT_PERIOD = "current_period"
    #: Rolling window ending at, and including, the current period.
    ROLLING_3 = "rolling_3_periods"
    #: Everything up to and including the current period.
    CUMULATIVE = "cumulative"
    #: Difference against the immediately preceding period.
    DELTA_1 = "delta_vs_previous"


@dataclass(frozen=True, slots=True)
class Feature:
    name: str
    description: str
    window: Window
    minimum: float
    maximum: float
    #: Value used when the source is NULL. For every feature here, a NULL means
    #: «no activity», and zero is its honest reading.
    null_default: float = 0.0
    #: Where it is computed. One place, always.
    source: str = "gold.mart_player_behaviour_features"

    def validate(self, value: float) -> None:
        if not (self.minimum <= value <= self.maximum):
            raise ValueError(
                f"feature {self.name!r} = {value} is outside its declared range "
                f"[{self.minimum}, {self.maximum}]"
            )


#: Declared features, in no particular order — order is owned by the model card,
#: because that is what the ONNX tensor is built from.
FEATURES: dict[str, Feature] = {
    f.name: f
    for f in (
        Feature(
            "essential_coverage",
            "Share of the period's mandatory needs actually bought.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "plan_adherence",
            "1.0 when the fact matched the plan exactly; decays with deviation.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "savings_rate",
            "Coins moved to savings as a share of coins available.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "optional_spend_share",
            "Optional spending as a share of all spending.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "rejected_purchases",
            "Purchases blocked for insufficient funds in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            100.0,
        ),
        Feature(
            "withdrawals",
            "Withdrawals from goal savings in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            100.0,
        ),
        Feature(
            "revisions_count",
            "How many times the child edited the plan before confirming it.",
            Window.CURRENT_PERIOD,
            0.0,
            100.0,
        ),
        Feature(
            "purchases_essential",
            "Count of essential purchases in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            200.0,
        ),
        Feature(
            "purchases_optional",
            "Count of optional purchases in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            200.0,
        ),
        Feature(
            "quests_completed",
            "Quests finished in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            50.0,
        ),
        Feature(
            "quest_outcome_score",
            "Mean quest outcome: 1.0 optimal, 0.5 suboptimal, 0.0 poor.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "spend_to_income_ratio",
            "Coins spent divided by coins earned in the period.",
            Window.CURRENT_PERIOD,
            0.0,
            50.0,
        ),
        Feature(
            "unallocated_share",
            "Share of the budget the plan left unassigned.",
            Window.CURRENT_PERIOD,
            0.0,
            1.0,
        ),
        Feature(
            "avg_essential_coverage_w",
            "Mean essential coverage over the behaviour window.",
            Window.ROLLING_3,
            0.0,
            1.0,
        ),
        Feature(
            "avg_plan_adherence_w",
            "Mean plan adherence over the behaviour window.",
            Window.ROLLING_3,
            0.0,
            1.0,
        ),
        Feature(
            "avg_savings_rate_w",
            "Mean savings rate over the behaviour window.",
            Window.ROLLING_3,
            0.0,
            1.0,
        ),
        Feature(
            "avg_optional_share_w",
            "Mean optional-spend share over the behaviour window.",
            Window.ROLLING_3,
            0.0,
            1.0,
        ),
        Feature(
            "plan_adherence_volatility",
            "Standard deviation of plan adherence over the window. Separates the "
            "erratic «explorer» from everyone else better than any single value.",
            Window.ROLLING_3,
            0.0,
            1.0,
        ),
        Feature(
            "savings_regularity",
            "Share of completed periods in which anything was saved.",
            Window.CUMULATIVE,
            0.0,
            1.0,
        ),
        Feature(
            "plan_adherence_delta_filled",
            "Change in plan adherence against the previous period. Positive means improving.",
            Window.DELTA_1,
            -1.0,
            1.0,
        ),
    )
}


def get(name: str) -> Feature:
    """Look up a declared feature, or fail loudly."""
    try:
        return FEATURES[name]
    except KeyError:
        raise KeyError(
            f"feature {name!r} is not declared in the registry. "
            "Add it to features/registry.py before a model consumes it — an "
            "undeclared feature has no owner, no range and no point-in-time rule."
        ) from None


def validate_row(values: dict[str, float]) -> list[str]:
    """Check one feature vector against the declared ranges.

    Returns the problems rather than raising: serving must degrade to the
    rule-based path on a bad vector, not crash the advisor.
    """
    problems: list[str] = []
    for name, value in values.items():
        feature = FEATURES.get(name)
        if feature is None:
            problems.append(f"{name}: not declared in the registry")
            continue
        try:
            feature.validate(value)
        except ValueError as exc:
            problems.append(str(exc))
    return problems


def describe() -> list[dict[str, str]]:
    """Registry as rows, for the CLI and for documentation."""
    return [
        {
            "feature": f.name,
            "window": f.window.value,
            "range": f"[{f.minimum:g}, {f.maximum:g}]",
            "source": f.source,
            "description": f.description,
        }
        for f in sorted(FEATURES.values(), key=lambda f: (f.window.value, f.name))
    ]
