"""Training with quality gates.

Three models, each with an explicit gate. A model that fails its gate is saved
(so the failure is auditable) but never promoted to ``latest``, and the CLI
exits non-zero — so CI cannot ship a regression.

Gates are compared against a **baseline**, not against an absolute number in
isolation. «85% accuracy» means nothing until you know the majority class is
32%; the baseline comparison is the part that tells you the model learned
something.

Why scikit-learn's ``HistGradientBoosting`` rather than LightGBM: it is the same
family of algorithm, it converts to ONNX through ``skl2onnx`` without an extra
toolchain, and the export path is what actually has to work here — these models
run on a mid-range Android phone, not on a server.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from monetka.common.config import get_settings
from monetka.common.logging import get_logger
from monetka.ml import features as feat
from monetka.ml.registry import ModelCard, data_fingerprint, new_version, save_model

log = get_logger("ml.train")


@dataclass(slots=True)
class TrainResult:
    name: str
    metrics: dict[str, float] = field(default_factory=dict)
    passed_gate: bool = False
    detail: str = ""
    #: Whether this version replaced the incumbent, and why. Passing the gate is
    #: necessary but not sufficient — see registry.decide_promotion.
    promotion: dict[str, object] = field(default_factory=dict)

    @property
    def promoted(self) -> bool:
        return bool(self.promotion.get("promoted"))


@contextmanager
def deterministic_fit() -> Iterator[None]:
    """Pin BLAS/OpenMP to one thread for the duration of a fit.

    ``HistGradientBoosting`` builds its histograms in parallel, and summing
    floats in a thread-dependent order gives bit-different totals. Near a split
    threshold that is enough to choose a different feature value, so the *same
    data and the same seed* produce slightly different trees between runs —
    which showed up downstream as ONNX parity metrics drifting by a few tenths
    of a percent, and would have made the model registry's reproducibility claim
    untrue.

    ``random_state`` does not cover this: the randomness is in the thread
    scheduling, not in the sampler. Single-threaded fitting is the cost of being
    able to say that a given dataset produces a given model, which is exactly
    what a gate-and-promote workflow has to be able to say.
    """
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1):
        yield


# --------------------------------------------------------------------------
# 1. Behaviour segment
# --------------------------------------------------------------------------


def train_behaviour_segment() -> TrainResult:
    """Classify the player's behaviour pattern for the current period.

    Used to choose *which explanation to show*. It cannot change the balance,
    block a purchase or affect the pet — see docs/ml-cards/behaviour_segment.md.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score, classification_report, f1_score

    settings = get_settings()
    frame = feat.load_behaviour_frame()
    dataset = feat.split_by_profile(frame)

    model = HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.08,
        max_depth=6,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=settings.random_seed,
    )
    with deterministic_fit():
        model.fit(dataset.x_train, dataset.y_train)

    predictions = model.predict(dataset.x_test)
    accuracy = float(accuracy_score(dataset.y_test, predictions))
    macro_f1 = float(f1_score(dataset.y_test, predictions, average="macro"))

    # Baseline: always predict the most common archetype. Beating this is the
    # minimum bar for claiming the model learned anything at all.
    majority = dataset.y_train.value_counts(normalize=True).iloc[0]
    baseline_accuracy = float((dataset.y_test == dataset.y_train.value_counts().idxmax()).mean())

    metrics = {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "baseline_accuracy": baseline_accuracy,
        "lift_over_baseline": accuracy - baseline_accuracy,
        "majority_class_share": float(majority),
    }
    passed = (
        accuracy >= settings.min_model_accuracy
        and macro_f1 >= 0.70
        and accuracy > baseline_accuracy + 0.15
    )

    log.info("behaviour_report", report=classification_report(dataset.y_test, predictions))

    card = ModelCard(
        name="behaviour_segment",
        version=new_version(),
        created_at=pd.Timestamp.now(tz="UTC").isoformat(),
        framework="scikit-learn/HistGradientBoostingClassifier",
        task="Choose which explanation to show the child, based on the period's behaviour pattern.",
        feature_names=list(dataset.feature_names),
        class_names=sorted(frame["label"].unique().tolist()),
        metrics=metrics,
        gates={
            "min_accuracy": settings.min_model_accuracy,
            "min_macro_f1": 0.70,
            "min_lift_over_baseline": 0.15,
        },
        applicability={
            "max_period_no": feat.BEHAVIOUR_MAX_PERIOD,
            "abstain_outside_range": True,
            "rationale": (
                "Archetypes converge as children learn; held-out accuracy falls "
                "from 0.89 at period 3 to 0.54 at period 12. Beyond the horizon "
                "the model abstains and the rule-based hint is used."
            ),
        },
        passed_gate=passed,
        training_rows=len(dataset.x_train),
        training_profiles=int(dataset.groups_train.nunique()),
        data_fingerprint=data_fingerprint(len(frame), sorted(dataset.feature_names)),
        notes=(
            "Advisory only. Output selects hint text; it never alters balance, "
            "purchases, savings or pet state. Falls back to a rule-based hint."
        ),
    )
    save_model(model, card)

    return TrainResult(
        "behaviour_segment",
        metrics,
        passed,
        f"accuracy={accuracy:.3f} vs baseline={baseline_accuracy:.3f}",
        promotion=card.promotion,
    )


# --------------------------------------------------------------------------
# 2. Quest recommender
# --------------------------------------------------------------------------


def train_quest_recommender() -> TrainResult:
    """Predict how well a player will do on a quest, given their recent state.

    The prediction is an *input* to the recommendation rule, not the rule. The
    rule itself is deterministic and lives in `serving/recommender.py`: cover
    the weakest competency first, never exceed the age-appropriate difficulty,
    and guarantee all three mandatory topics appear (ТЗ §2.5.8).
    """
    from scipy.stats import spearmanr
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    settings = get_settings()
    frame = feat.load_quest_frame()
    if frame.empty:
        return TrainResult("quest_recommender", {}, False, "no training rows")

    numeric = [
        "difficulty",
        "avg_plan_adherence_w",
        "avg_essential_coverage_w",
        "avg_savings_rate_w",
        "prior_outcome_score",
        "periods_completed",
    ]
    categorical = ["topic"]
    # float32 at training time, not just at inference.
    #
    # HistGradientBoosting bins each feature and stores the split thresholds as
    # midpoints between observed values. Train on float64 and infer on float32 —
    # which is what the phone does — and a value sitting on a bin edge can land
    # on the other side of *every* tree at once. Measured effect: 4.4% of rows
    # diverged, the worst by 0.23 on a 0-1 scale. That is not rounding noise,
    # and no export tolerance could honestly absorb it.
    #
    # Casting here makes the thresholds themselves float32-derived, so training
    # and on-device inference see identical bins. The classifier was already
    # trained this way, which is why its parity was exact while this model's was
    # not — the asymmetry is what gave the cause away.
    frame[numeric] = frame[numeric].fillna(0.0).astype(np.float32)

    groups = frame["profile_pseudo_id"].astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=settings.random_seed)
    train_idx, test_idx = next(splitter.split(frame, groups=groups))
    train, test = frame.iloc[train_idx], frame.iloc[test_idx]

    pipeline = Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        (
                            "cat",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            categorical,
                        ),
                    ],
                    remainder="passthrough",
                ),
            ),
            (
                "model",
                HistGradientBoostingRegressor(
                    max_iter=200,
                    learning_rate=0.08,
                    max_depth=5,
                    random_state=settings.random_seed,
                ),
            ),
        ]
    )
    columns = categorical + numeric
    with deterministic_fit():
        pipeline.fit(train[columns], train["target_outcome_score"])

    predictions = pipeline.predict(test[columns])
    mae = float(mean_absolute_error(test["target_outcome_score"], predictions))
    # Baseline: predict the global mean outcome. If the model cannot beat that,
    # a constant is cheaper, more predictable and more honest.
    baseline_mae = float(
        mean_absolute_error(
            test["target_outcome_score"],
            np.full(len(test), train["target_outcome_score"].mean()),
        )
    )

    # Rank correlation is the metric that matches how this model is used.
    # A child's choice is a draw, not a deterministic function of their state,
    # so most of the target's variance is irreducible and MAE is dominated by
    # noise — the measured gap to a constant predictor is only ~3%. What the
    # recommender actually needs is the right *ordering* of candidate quests,
    # so that is what is gated; MAE stays as a sanity check that the model has
    # not simply learned to rank while predicting nonsense.
    rho, p_value = spearmanr(predictions, test["target_outcome_score"])
    rho = float(rho)

    metrics = {
        "spearman_rho": rho,
        "spearman_p_value": float(p_value),
        "mae": mae,
        "baseline_mae": baseline_mae,
        "mae_improvement": baseline_mae - mae,
    }
    passed = rho >= 0.10 and p_value < 0.01 and mae < baseline_mae

    card = ModelCard(
        name="quest_recommender",
        version=new_version(),
        created_at=pd.Timestamp.now(tz="UTC").isoformat(),
        framework="scikit-learn/HistGradientBoostingRegressor",
        task="Score candidate quests so the deterministic recommender can rank them.",
        feature_names=columns,
        metrics=metrics,
        gates={"min_spearman_rho": 0.10, "max_p_value": 0.01, "mae_below_baseline": True},
        passed_gate=passed,
        training_rows=len(train),
        training_profiles=int(train["profile_pseudo_id"].nunique()),
        data_fingerprint=data_fingerprint(len(frame), sorted(columns)),
        notes=(
            "Ranking aid only. Hard constraints (age-appropriate difficulty, "
            "coverage of all three mandatory topics) are enforced by rules "
            "downstream and cannot be overridden by the score."
        ),
    )
    save_model(pipeline, card)

    return TrainResult(
        "quest_recommender",
        metrics,
        passed,
        f"ρ={rho:.3f}, MAE={mae:.4f} vs {baseline_mae:.4f}",
        promotion=card.promotion,
    )


# --------------------------------------------------------------------------
# 3. Economy anomaly
# --------------------------------------------------------------------------


def train_economy_anomaly() -> TrainResult:
    """Flag game periods whose economy looks mis-balanced.

    Strictly an internal tool for the methodologist. It is never shown to a
    child and never changes the game — it opens a ticket, not a dialog.
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    settings = get_settings()
    frame = feat.load_economy_frame()
    if len(frame) < 4:
        return TrainResult(
            "economy_anomaly", {}, False, f"only {len(frame)} periods; need ≥4 to fit"
        )

    columns = [c for c in frame.columns if c != "period_no"]
    pipeline = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "model",
                IsolationForest(
                    n_estimators=200,
                    contamination=0.15,
                    random_state=settings.random_seed,
                ),
            ),
        ]
    )
    with deterministic_fit():
        pipeline.fit(frame[columns])
    flags = pipeline.predict(frame[columns])
    flagged_share = float((flags == -1).mean())

    metrics = {
        "periods_evaluated": float(len(frame)),
        "flagged_share": flagged_share,
        "flagged_count": float((flags == -1).sum()),
    }
    # The gate is a sanity bound, not a skill score: an unsupervised detector
    # that flags most periods is noise, and one that flags none is asleep.
    passed = 0.0 < flagged_share <= 0.35

    card = ModelCard(
        name="economy_anomaly",
        version=new_version(),
        created_at=pd.Timestamp.now(tz="UTC").isoformat(),
        framework="scikit-learn/IsolationForest",
        task="Surface mis-balanced game periods for human review by the methodologist.",
        feature_names=columns,
        metrics=metrics,
        gates={"flagged_share_between": [0.0, 0.35]},
        passed_gate=passed,
        training_rows=len(frame),
        data_fingerprint=data_fingerprint(len(frame), sorted(columns)),
        notes="Internal only. Never surfaced to a child; output is a review queue.",
    )
    save_model(pipeline, card)

    return TrainResult(
        "economy_anomaly",
        metrics,
        passed,
        f"{flagged_share:.1%} of periods flagged",
        promotion=card.promotion,
    )


TRAINERS = {
    "behaviour": train_behaviour_segment,
    "quest": train_quest_recommender,
    "economy": train_economy_anomaly,
}


def train_models(which: str = "all") -> list[TrainResult]:
    """Train one model or all of them."""
    selected = TRAINERS if which == "all" else {which: TRAINERS[which]}
    results = []
    for name, trainer in selected.items():
        log.info("training_started", model=name)
        result = trainer()
        log.info(
            "training_finished",
            model=result.name,
            passed_gate=result.passed_gate,
            detail=result.detail,
        )
        results.append(result)
    return results
