"""Production model monitoring.

Offline metrics describe a held-out split of the training data. This module
describes the model that is actually running, from the prediction log the device
emits (`hint_shown` → `silver.fct_hint`).

Two questions, answered separately because they have different requirements:

**Is the deployment healthy?**  Consult rate, latency, prediction distribution.
No labels needed, available immediately, and this is what catches a broken
release. A model that suddenly predicts one class for everybody has a broken
feature pipeline, and that shows up here long before any outcome does.

**Is it doing any good?**  Compared against the control cohort. Two traps make
this easy to get wrong, and both are handled explicitly below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from monetka.common.config import get_settings
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect

log = get_logger("monitoring.performance")

#: On-device inference budget. ТЗ §3.4 allows a second for a visible response to
#: a local action; a model anywhere near that has already ruined the interaction.
LATENCY_BUDGET_MS = 50

#: Below this share of hints being model-chosen, personalisation is effectively
#: not deployed and the cohort comparison has nothing to measure.
MIN_CONSULT_RATE = 0.05

#: A prediction distribution more concentrated than this means the model has
#: collapsed onto one class — almost always a broken feature pipeline.
MAX_CLASS_CONCENTRATION = 0.80


@dataclass(frozen=True, slots=True)
class Health:
    """Operational state of the deployed model. No labels required."""

    hints_total: int
    model_consults: int
    consult_rate: float
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    slow_inferences: int
    distinct_hints: int
    top_class_share: float | None
    predicted_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def problems(self) -> list[str]:
        issues: list[str] = []
        if self.consult_rate < MIN_CONSULT_RATE:
            issues.append(
                f"model chose only {self.consult_rate:.1%} of hints "
                f"(min {MIN_CONSULT_RATE:.0%}) — personalisation is effectively off"
            )
        if self.p95_latency_ms is not None and self.p95_latency_ms > LATENCY_BUDGET_MS:
            issues.append(
                f"p95 latency {self.p95_latency_ms:.0f} ms exceeds the "
                f"{LATENCY_BUDGET_MS} ms on-device budget"
            )
        if self.top_class_share is not None and self.top_class_share > MAX_CLASS_CONCENTRATION:
            issues.append(
                f"{self.top_class_share:.0%} of predictions are one class — "
                "suspect a broken feature pipeline"
            )
        if self.distinct_hints <= 1 and self.hints_total > 50:
            issues.append("every hint is identical — the advisor has collapsed")
        return issues

    @property
    def healthy(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class CohortEffect:
    """Intention-to-treat comparison between the two advisor cohorts."""

    metric: str
    model_profiles: int
    rule_profiles: int
    model_mean: float
    rule_mean: float
    difference: float
    ci_low: float
    ci_high: float
    pooled_sd: float
    required_n_per_arm: int | None

    @property
    def significant(self) -> bool:
        """True when the 95% interval excludes zero."""
        return self.ci_low > 0.0 or self.ci_high < 0.0

    @property
    def verdict(self) -> str:
        if not self.significant:
            return "no detectable difference"
        return "model cohort better" if self.difference > 0 else "model cohort worse"

    @property
    def note(self) -> str:
        """What to do about the result — the part a verdict alone leaves out."""
        if self.significant:
            return "effect detected"
        if self.required_n_per_arm is None:
            return "effect indistinguishable from zero"
        if self.required_n_per_arm <= min(self.model_profiles, self.rule_profiles):
            return "well powered — the effect really is ~zero"
        return f"underpowered: needs ≈{self.required_n_per_arm:,} profiles per arm"


@dataclass(slots=True)
class MonitoringReport:
    health: Health
    effects: list[CohortEffect] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.health.healthy


def load_health(period_from: int = 0) -> Health:
    """Operational health of the deployed model, from the prediction log."""
    with connect(read_only=True) as conn:
        row = conn.execute(
            """
            SELECT
                count(*)                                           AS hints_total,
                count(*) FILTER (WHERE hint_source = 'model')      AS model_consults,
                avg(inference_latency_ms)                          AS avg_latency,
                quantile_cont(inference_latency_ms, 0.95)          AS p95_latency,
                count(*) FILTER (WHERE inference_latency_ms > ?)   AS slow,
                count(DISTINCT hint_id)                            AS distinct_hints
            FROM silver.fct_hint
            WHERE NOT demo_mode AND period_no >= ?
            """,
            [LATENCY_BUDGET_MS, period_from],
        ).fetchone()

        distribution = dict(
            conn.execute(
                """
                SELECT predicted_segment, count(*)
                FROM silver.fct_hint
                WHERE NOT demo_mode AND period_no >= ?
                  AND predicted_segment IS NOT NULL
                GROUP BY 1
                """,
                [period_from],
            ).fetchall()
        )

    if row is None:  # pragma: no cover - an aggregate always returns a row
        row = (0, 0, None, None, 0, 0)

    hints_total = int(row[0] or 0)
    consults = int(row[1] or 0)
    total_predictions = sum(distribution.values())

    return Health(
        hints_total=hints_total,
        model_consults=consults,
        consult_rate=consults / hints_total if hints_total else 0.0,
        avg_latency_ms=float(row[2]) if row[2] is not None else None,
        p95_latency_ms=float(row[3]) if row[3] is not None else None,
        slow_inferences=int(row[4] or 0),
        distinct_hints=int(row[5] or 0),
        top_class_share=(
            max(distribution.values()) / total_predictions if total_predictions else None
        ),
        predicted_distribution=distribution,
    )


def _profile_level_outcomes() -> pd.DataFrame:
    """One row per profile — the unit the cohort was randomised at.

    Aggregating to the profile before comparing is not a detail. There are ten
    hint rows per profile, and rows from the same child are not independent
    observations: treating them as such (pseudo-replication) inflates the sample
    tenfold and shrinks every confidence interval to nothing, which manufactures
    significance out of noise.
    """
    with connect(read_only=True) as conn:
        return conn.execute(
            """
            WITH hinted AS (
                SELECT
                    h.profile_pseudo_id,
                    h.advisor_arm,
                    h.period_no,
                    after.plan_adherence     AS adherence_after,
                    after.essential_coverage AS coverage_after,
                    after.savings_rate       AS savings_rate_after
                FROM silver.fct_hint h
                JOIN gold.mart_period_summary after
                  ON after.profile_pseudo_id = h.profile_pseudo_id
                 AND after.period_no = h.period_no + 1
                WHERE NOT h.demo_mode
            )
            SELECT
                profile_pseudo_id,
                any_value(advisor_arm)              AS advisor_arm,
                avg(adherence_after)                AS plan_adherence,
                avg(coverage_after)                 AS essential_coverage,
                avg(coalesce(savings_rate_after,0)) AS savings_rate
            FROM hinted
            GROUP BY profile_pseudo_id
            ORDER BY profile_pseudo_id
            """
        ).fetch_df()


def _welch_interval(
    a: pd.Series, b: pd.Series, confidence: float = 0.95
) -> tuple[float, float, float]:
    """Difference in means with a Welch confidence interval.

    Welch rather than Student: the two cohorts need not have equal variance, and
    assuming they do is a free way to be wrong.
    """
    from scipy import stats

    mean_a, mean_b = float(a.mean()), float(b.mean())
    diff = mean_a - mean_b

    var_a, var_b = a.var(ddof=1), b.var(ddof=1)
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return diff, float("nan"), float("nan")

    standard_error = math.sqrt(var_a / n_a + var_b / n_b)
    if standard_error == 0:
        return diff, diff, diff

    degrees = (var_a / n_a + var_b / n_b) ** 2 / (
        (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    )
    critical = stats.t.ppf(0.5 + confidence / 2, degrees)
    margin = critical * standard_error
    return diff, diff - margin, diff + margin


def compare_cohorts(
    metrics: tuple[str, ...] = ("plan_adherence", "essential_coverage", "savings_rate"),
) -> list[CohortEffect]:
    """Intention-to-treat comparison of the personalised and control cohorts.

    Intention-to-treat means every profile counts in the cohort it was assigned
    to, whether or not the model ended up acting for it. Filtering to profiles
    the model actually served would reintroduce exactly the selection bias this
    comparison exists to avoid — the model only acts for children already doing
    well, so that subset is not comparable to anything.
    """
    frame = _profile_level_outcomes()
    if frame.empty:
        log.warning("no_outcomes_to_compare")
        return []

    model = frame[frame["advisor_arm"] == "model"]
    rule = frame[frame["advisor_arm"] == "rule"]
    if model.empty or rule.empty:
        log.warning("cohort_missing", model=len(model), rule=len(rule))
        return []

    effects: list[CohortEffect] = []
    for metric in metrics:
        diff, low, high = _welch_interval(model[metric], rule[metric])
        pooled_sd = float(math.sqrt((model[metric].var(ddof=1) + rule[metric].var(ddof=1)) / 2))
        effects.append(
            CohortEffect(
                metric=metric,
                model_profiles=len(model),
                rule_profiles=len(rule),
                model_mean=float(model[metric].mean()),
                rule_mean=float(rule[metric].mean()),
                difference=diff,
                ci_low=low,
                ci_high=high,
                pooled_sd=pooled_sd,
                required_n_per_arm=_required_sample_size(diff, pooled_sd),
            )
        )
    return effects


#: (z(0.975) + z(0.80))² — the constant in the two-sample size formula for a
#: 5% false-positive rate and 80% power.
_POWER_CONSTANT = (1.959964 + 0.841621) ** 2


def _required_sample_size(difference: float, pooled_sd: float) -> int | None:
    """Profiles per arm needed to detect an effect this size at 80% power.

    Turns «no detectable difference» into something actionable. Without it, an
    inconclusive result is indistinguishable from a null one, and teams
    routinely read the first as the second and ship on that basis.
    """
    if pooled_sd <= 0 or difference == 0:
        return None
    n = 2 * _POWER_CONSTANT * (pooled_sd / abs(difference)) ** 2
    if not math.isfinite(n) or n > 10_000_000:
        return None
    return math.ceil(n)


def run_monitoring(period_from: int = 0) -> MonitoringReport:
    """Full report: operational health plus the cohort comparison."""
    settings = get_settings()
    health = load_health(period_from)
    effects = compare_cohorts()

    log.info(
        "monitoring_report",
        hints=health.hints_total,
        consult_rate=round(health.consult_rate, 3),
        p95_latency_ms=health.p95_latency_ms,
        healthy=health.healthy,
        problems=health.problems,
        environment=settings.env,
    )
    return MonitoringReport(health=health, effects=effects)
