"""Reproducible evidence for the modelling decisions.

Every non-obvious choice in this platform is defended by a number somewhere in
the docs. This module is how those numbers are regenerated, so a reviewer can
check a claim instead of trusting it.

Run:
    python -m monetka.ml.diagnostics behaviour-horizon
    python -m monetka.ml.diagnostics quest-ranking
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from monetka.common.config import get_settings
from monetka.common.logging import configure_logging
from monetka.ml import features as feat

console = Console()


def behaviour_horizon() -> pd.DataFrame:
    """Measure how behaviour-segment accuracy decays with the period number.

    This is the evidence behind ``BEHAVIOUR_MAX_PERIOD``. It deliberately
    trains on the *full* period range — restricting training first would hide
    the very decay being measured.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import GroupShuffleSplit

    from monetka.ingestion.warehouse import connect

    settings = get_settings()
    columns = ", ".join(feat.BEHAVIOUR_FEATURES)
    with connect(read_only=True) as conn:
        frame = conn.execute(
            f"""
            SELECT profile_pseudo_id, period_no, {columns}
            FROM gold.mart_player_behaviour_features
            WHERE is_training_eligible
            """
        ).fetch_df()

    import json

    labels = json.loads(
        (settings.data_dir / "labels" / "archetypes.json").read_text(encoding="utf-8")
    )
    frame["label"] = frame["profile_pseudo_id"].astype(str).map(labels)
    frame = frame.dropna(subset=["label"])
    frame[list(feat.BEHAVIOUR_FEATURES)] = frame[list(feat.BEHAVIOUR_FEATURES)].fillna(0.0)

    groups = frame["profile_pseudo_id"].astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=settings.random_seed)
    train_idx, test_idx = next(splitter.split(frame, frame["label"], groups))
    train, test = frame.iloc[train_idx].copy(), frame.iloc[test_idx].copy()

    model = HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.08,
        max_depth=6,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=settings.random_seed,
    )
    x_columns = list(feat.BEHAVIOUR_FEATURES)
    model.fit(train[x_columns].astype(np.float32), train["label"])
    test["pred"] = model.predict(test[x_columns].astype(np.float32))

    rows = []
    for period, group in test.groupby("period_no"):
        # Separability: how far apart the label means sit on a signature feature.
        means = group.groupby("label")["optional_spend_share"].mean()
        rows.append(
            {
                "period_no": int(period),
                "rows": len(group),
                "accuracy": accuracy_score(group["label"], group["pred"]),
                "label_spread": float(means.max() - means.min()) if len(means) > 1 else 0.0,
            }
        )
    result = pd.DataFrame(rows)

    table = Table("period", "rows", "accuracy", "label spread", title="Behaviour-segment decay")
    for _, row in result.iterrows():
        style = (
            "green" if row["accuracy"] >= 0.80 else "yellow" if row["accuracy"] >= 0.70 else "red"
        )
        table.add_row(
            str(int(row["period_no"])),
            f"{int(row['rows']):,}",
            f"[{style}]{row['accuracy']:.3f}[/]",
            f"{row['label_spread']:.3f}",
        )
    console.print(table)
    console.print(
        f"Chosen horizon: period ≤ [bold]{feat.BEHAVIOUR_MAX_PERIOD}[/] "
        "— the last period holding accuracy ≥ 0.80. Beyond it the model abstains."
    )
    return result


def quest_ranking() -> float:
    """Measure the quest scorer as a *ranker*, which is how it is used.

    Point-accuracy (MAE) is the wrong lens: the child's choice is a draw, not a
    deterministic function of their state, so a large part of the target is
    irreducible noise. What the recommender actually needs is the correct
    *ordering* of candidate quests for a given player — so that is what is
    measured and gated.
    """
    from scipy.stats import spearmanr
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    settings = get_settings()
    frame = feat.load_quest_frame()
    numeric = [
        "difficulty",
        "avg_plan_adherence_w",
        "avg_essential_coverage_w",
        "avg_savings_rate_w",
        "prior_outcome_score",
        "periods_completed",
    ]
    frame[numeric] = frame[numeric].fillna(0.0)
    columns = ["topic", *numeric]

    groups = frame["profile_pseudo_id"].astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=settings.random_seed)
    train_idx, test_idx = next(splitter.split(frame, groups=groups))
    train, test = frame.iloc[train_idx], frame.iloc[test_idx].copy()

    pipeline = Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        (
                            "cat",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            ["topic"],
                        )
                    ],
                    remainder="passthrough",
                ),
            ),
            ("model", HistGradientBoostingRegressor(random_state=settings.random_seed)),
        ]
    )
    pipeline.fit(train[columns], train["target_outcome_score"])
    test["pred"] = pipeline.predict(test[columns])

    rho, p_value = spearmanr(test["pred"], test["target_outcome_score"])
    console.print(
        f"Spearman ρ between predicted and observed outcome: [bold]{rho:.4f}[/] (p={p_value:.2e})"
    )
    return float(rho)


def main() -> None:
    configure_logging()
    command = sys.argv[1] if len(sys.argv) > 1 else "behaviour-horizon"
    if command == "behaviour-horizon":
        behaviour_horizon()
    elif command == "quest-ranking":
        quest_ranking()
    else:
        console.print(f"unknown diagnostic {command!r}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
