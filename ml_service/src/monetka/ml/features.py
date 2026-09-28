"""Assembling training datasets from the gold layer.

The feature *definitions* live in SQL (``mart_player_behaviour_features``), not
in Python. That is deliberate: the same definition has to be computed twice —
offline for training, and on device for inference — and a definition expressed
as a dbt model can be read, tested and diffed by anyone. A definition buried in
a pandas pipeline cannot.

This module only *reads* those features and attaches labels. The one piece of
logic it owns is the split, which is where this kind of dataset is easiest to
get wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from monetka.common.config import get_settings
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect

log = get_logger("ml.features")

#: Columns fed to the behaviour-segment model. Listed explicitly rather than
#: "everything except the label": a new column appearing in the mart must be an
#: intentional feature decision, not an accident that silently changes the model.
BEHAVIOUR_FEATURES: tuple[str, ...] = (
    "essential_coverage",
    "plan_adherence",
    "savings_rate",
    "optional_spend_share",
    "rejected_purchases",
    "withdrawals",
    "revisions_count",
    "purchases_essential",
    "purchases_optional",
    "quests_completed",
    "quest_outcome_score",
    "spend_to_income_ratio",
    "unallocated_share",
    "avg_essential_coverage_w",
    "avg_plan_adherence_w",
    "avg_savings_rate_w",
    "avg_optional_share_w",
    "plan_adherence_volatility",
    "savings_regularity",
    "plan_adherence_delta_filled",
)

BEHAVIOUR_LABELS: tuple[str, ...] = ("planner", "spender", "saver", "explorer")

#: Last period in which the behaviour segment is still identifiable.
#:
#: This is a measured limit, not a tuning knob. As children learn, the
#: archetypes converge: the spread of `optional_spend_share` between the four
#: labels falls from 0.19 at period 3 to 0.05 at period 10, and held-out
#: accuracy falls with it — 0.89 at period 3, 0.48 at period 10. By the end of
#: the horizon a «spender» genuinely behaves like a «planner», which is the
#: intervention succeeding, not the model failing.
#:
#: The horizon moved from 6 to 5 when the advisor started nudging behaviour.
#: That is the model limiting its own usefulness, and it is worth stating
#: plainly: the better the hints work, the sooner children stop being
#: distinguishable, and the sooner the model has nothing left to say. Measured
#: accuracy at period 6 fell from 0.838 to 0.747 once hints were in the loop.
#:
#: The product consequence is that this model is an *early-detection* tool. It
#: earns its place in the first few periods, when a child is still forming
#: habits and a targeted hint changes something. Past the horizon the honest
#: answer is abstention: the serving layer returns UNKNOWN and the rule-based
#: hint — which at that point is «you are doing well, keep going» — is simply
#: the correct thing to say.
#:
#: Reproduce with: `python -m monetka.ml.diagnostics behaviour-horizon`
BEHAVIOUR_MAX_PERIOD = 5


@dataclass(frozen=True, slots=True)
class Dataset:
    """A grouped train/test split, kept together so nothing drifts apart."""

    x_train: pd.DataFrame
    x_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series
    groups_train: pd.Series
    groups_test: pd.Series
    feature_names: tuple[str, ...]

    def summary(self) -> dict[str, int]:
        return {
            "train_rows": len(self.x_train),
            "test_rows": len(self.x_test),
            "train_profiles": self.groups_train.nunique(),
            "test_profiles": self.groups_test.nunique(),
        }


def load_behaviour_frame() -> pd.DataFrame:
    """Read eligible feature rows and join the archetype labels."""
    settings = get_settings()

    with connect(read_only=True) as conn:
        frame = conn.execute(
            f"""
            SELECT profile_pseudo_id, period_no, {", ".join(BEHAVIOUR_FEATURES)}
            FROM gold.mart_player_behaviour_features
            WHERE is_training_eligible
              AND period_no <= {BEHAVIOUR_MAX_PERIOD}
            -- ORDER BY is load-bearing, not cosmetic. DuckDB makes no ordering
            -- promise without it, and a parallel scan genuinely returns rows in
            -- a different order between runs. That would change the train/test
            -- split, the fitted model and every reported metric — reproducibility
            -- would be a claim the code does not actually keep.
            ORDER BY profile_pseudo_id, period_no
            """
        ).fetch_df()

    labels_path = settings.data_dir / "labels" / "archetypes.json"
    if not labels_path.exists():
        raise FileNotFoundError(
            f"{labels_path} not found — run `monetka generate` first. "
            "Labels are produced by the simulator and never derived from telemetry."
        )
    labels: dict[str, str] = json.loads(labels_path.read_text(encoding="utf-8"))

    frame["label"] = frame["profile_pseudo_id"].astype(str).map(labels)
    missing = int(frame["label"].isna().sum())
    if missing:
        log.warning("rows_without_label", rows=missing)
        frame = frame.dropna(subset=["label"])

    # Features arrive from SQL with NULLs where a ratio had a zero denominator
    # (a period with no income, a player with no deposits). Zero is the correct
    # reading of "no activity" for every one of these columns.
    frame[list(BEHAVIOUR_FEATURES)] = frame[list(BEHAVIOUR_FEATURES)].fillna(0.0)

    log.info(
        "behaviour_frame_loaded", rows=len(frame), profiles=frame["profile_pseudo_id"].nunique()
    )
    return frame


def split_by_profile(frame: pd.DataFrame, test_size: float = 0.25) -> Dataset:
    """Split so that a profile appears in exactly one side.

    A naive row-wise split would put period 3 of a player in train and period 4
    in test. Those rows share rolling-window features and the same archetype, so
    the model would be scored on players it had already seen and the reported
    accuracy would be fiction. Splitting on the profile is the only honest
    option here.
    """
    from sklearn.model_selection import GroupShuffleSplit

    settings = get_settings()
    groups = frame["profile_pseudo_id"].astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=settings.random_seed)
    train_idx, test_idx = next(splitter.split(frame, frame["label"], groups))

    train, test = frame.iloc[train_idx], frame.iloc[test_idx]
    overlap = set(train["profile_pseudo_id"]) & set(test["profile_pseudo_id"])
    if overlap:  # pragma: no cover - guards against a future refactor
        raise AssertionError(f"{len(overlap)} profiles leaked across the split")

    dataset = Dataset(
        x_train=train[list(BEHAVIOUR_FEATURES)].astype(np.float32),
        x_test=test[list(BEHAVIOUR_FEATURES)].astype(np.float32),
        y_train=train["label"],
        y_test=test["label"],
        groups_train=train["profile_pseudo_id"].astype(str),
        groups_test=test["profile_pseudo_id"].astype(str),
        feature_names=BEHAVIOUR_FEATURES,
    )
    log.info("split_created", **dataset.summary())
    return dataset


def load_quest_frame() -> pd.DataFrame:
    """Rows for the quest recommender: player state × quest → observed outcome.

    The target is the outcome score the child achieved. The recommender scores
    unseen quests for a player and picks the one that best advances the weakest
    competency — the score is an input to that rule, never the decision itself.
    """
    with connect(read_only=True) as conn:
        return conn.execute(
            """
            SELECT
                f.profile_pseudo_id,
                f.period_no,
                q.quest_id,
                q.topic,
                q.difficulty,
                f.avg_plan_adherence_w,
                f.avg_essential_coverage_w,
                f.avg_savings_rate_w,
                f.quest_outcome_score      AS prior_outcome_score,
                f.periods_completed,
                q.outcome_score            AS target_outcome_score
            FROM silver.fct_quest_attempt q
            JOIN gold.mart_player_behaviour_features f
              ON f.profile_pseudo_id = q.profile_pseudo_id
             AND f.period_no = q.period_no - 1      -- state BEFORE the quest
            WHERE NOT q.demo_mode
            -- Deterministic order: see the note in load_behaviour_frame.
            ORDER BY f.profile_pseudo_id, f.period_no, q.quest_id
            """
        ).fetch_df()


#: Numeric features of the quest recommender, in the order the model expects.
#: Declared here so training and export cannot disagree about which columns are
#: numeric — they must be cast identically to float32 in both places.
QUEST_NUMERIC_FEATURES: tuple[str, ...] = (
    "difficulty",
    "avg_plan_adherence_w",
    "avg_essential_coverage_w",
    "avg_savings_rate_w",
    "prior_outcome_score",
    "periods_completed",
)
QUEST_CATEGORICAL_FEATURES: tuple[str, ...] = ("topic",)


def load_economy_frame() -> pd.DataFrame:
    """Per-period economy aggregates for the anomaly detector."""
    with connect(read_only=True) as conn:
        return conn.execute(
            """
            SELECT
                period_no,
                affordability_ratio,
                avg_essential_coverage,
                avg_plan_adherence,
                avg_savings_rate,
                rejections_per_period,
                share_hitting_limit,
                share_essentials_covered,
                share_saving,
                median_leftover
            FROM gold.mart_economy_health
            ORDER BY period_no
            """
        ).fetch_df()
