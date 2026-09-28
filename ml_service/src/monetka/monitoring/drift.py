"""Feature drift monitoring.

Drift here is not a hypothetical. The population *is expected* to drift, because
the product works: as children learn, plan adherence rises, savings become
regular and the behaviour distribution shifts towards «planner». A model trained
on early-period data will slowly stop matching the players it serves.

That makes the distinction that matters: **healthy drift** (the intervention is
working) versus **broken drift** (a content change unbalanced the economy, or a
release introduced a telemetry bug). The report below measures the shift; a
human reads it alongside `mart_economy_health` to decide which it is. Nothing is
retrained automatically — auto-retraining on a shifting population is how a
model quietly learns to reward whatever the last bug produced.

PSI (Population Stability Index) is used rather than a KS test because it is
readable: the conventional bands (<0.1 stable, 0.1-0.2 moderate, >0.2 material)
are easy to justify in a review, and the per-bin contributions say *where* the
distribution moved, not merely that it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from monetka.common.config import get_settings
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect
from monetka.ml.features import BEHAVIOUR_FEATURES

log = get_logger("monitoring.drift")

#: Bands from the standard PSI convention.
PSI_STABLE = 0.10
PSI_MATERIAL = 0.20


@dataclass(frozen=True, slots=True)
class FeatureDrift:
    feature: str
    psi: float
    drifted: bool
    reference_mean: float
    current_mean: float

    @property
    def band(self) -> str:
        if self.psi < PSI_STABLE:
            return "stable"
        if self.psi < PSI_MATERIAL:
            return "moderate"
        return "material"


@dataclass(slots=True)
class DriftReport:
    threshold: float
    reference_rows: int
    current_rows: int
    features: list[FeatureDrift] = field(default_factory=list)

    @property
    def drifted_count(self) -> int:
        return sum(1 for f in self.features if f.drifted)

    @property
    def worst(self) -> FeatureDrift | None:
        return max(self.features, key=lambda f: f.psi, default=None)


def population_stability_index(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """PSI between two samples.

    Bin edges come from the *reference* quantiles, which is the point: the
    reference defines what "normal" looked like, and the current sample is
    measured against that fixed ruler. Recomputing edges from the current data
    would hide exactly the shift being looked for.
    """
    reference = reference[np.isfinite(reference)]
    current = current[np.isfinite(current)]
    if reference.size == 0 or current.size == 0:
        return 0.0

    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if edges.size < 3:  # a near-constant feature cannot meaningfully drift
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    # Laplace smoothing: an empty bin must not produce an infinite PSI.
    ref_share = (ref_counts + 1) / (ref_counts.sum() + len(ref_counts))
    cur_share = (cur_counts + 1) / (cur_counts.sum() + len(cur_counts))

    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def run_drift_report(reference_periods: int = 4) -> DriftReport:
    """Compare the most recent periods against the earliest ones.

    The reference window is the first ``reference_periods`` periods — the
    population the model was trained on — and the current window is everything
    after it.
    """
    settings = get_settings()
    columns = ", ".join(BEHAVIOUR_FEATURES)

    with connect(read_only=True) as conn:
        frame: pd.DataFrame = conn.execute(
            f"SELECT period_no, {columns} FROM gold.mart_player_behaviour_features"
        ).fetch_df()

    reference = frame[frame["period_no"] <= reference_periods]
    current = frame[frame["period_no"] > reference_periods]

    report = DriftReport(
        threshold=settings.drift_psi_threshold,
        reference_rows=len(reference),
        current_rows=len(current),
    )
    if reference.empty or current.empty:
        log.warning(
            "drift_window_empty",
            reference_rows=len(reference),
            current_rows=len(current),
        )
        return report

    for feature in BEHAVIOUR_FEATURES:
        psi = population_stability_index(
            reference[feature].to_numpy(dtype=float),
            current[feature].to_numpy(dtype=float),
        )
        report.features.append(
            FeatureDrift(
                feature=feature,
                psi=psi,
                drifted=psi > settings.drift_psi_threshold,
                reference_mean=float(reference[feature].mean()),
                current_mean=float(current[feature].mean()),
            )
        )

    report.features.sort(key=lambda f: f.psi, reverse=True)
    log.info(
        "drift_report",
        drifted=report.drifted_count,
        total=len(report.features),
        worst=report.worst.feature if report.worst else None,
    )
    return report
