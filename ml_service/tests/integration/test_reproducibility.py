"""Reproducibility guarantees.

The README claims that an identical seed yields an identical dataset and an
identical model. That claim is only worth making if something enforces it, and
it is easy to break by accident: a query without ``ORDER BY`` is enough.

DuckDB gives no ordering promise for an unordered query, and a parallel scan
really does return rows in different orders between runs. That reorders the
train/test split, which changes the fitted model, which changes every reported
metric — while every seed in the code stays the same. These tests exist because
exactly that happened here.
"""

from __future__ import annotations

import pytest

from monetka.ml import features as feat

pytestmark = [pytest.mark.slow, pytest.mark.usefixtures("small_cohort_gold")]


def test_behaviour_frame_row_order_is_stable() -> None:
    first = feat.load_behaviour_frame()
    second = feat.load_behaviour_frame()
    assert list(first["profile_pseudo_id"].astype(str)) == list(
        second["profile_pseudo_id"].astype(str)
    )
    assert list(first["period_no"]) == list(second["period_no"])


def test_quest_frame_row_order_is_stable() -> None:
    first = feat.load_quest_frame()
    second = feat.load_quest_frame()
    assert list(first["quest_id"]) == list(second["quest_id"])
    assert list(first["profile_pseudo_id"].astype(str)) == list(
        second["profile_pseudo_id"].astype(str)
    )


def test_split_membership_is_stable_across_reloads() -> None:
    """Reloading the frame must not move a profile between train and test."""
    first = feat.split_by_profile(feat.load_behaviour_frame())
    second = feat.split_by_profile(feat.load_behaviour_frame())
    assert set(first.groups_test) == set(second.groups_test)


def test_behaviour_model_metrics_are_reproducible() -> None:
    """Training twice on the same warehouse must give the same numbers."""
    from monetka.ml.train import train_behaviour_segment

    first = train_behaviour_segment()
    second = train_behaviour_segment()
    assert first.metrics["accuracy"] == pytest.approx(second.metrics["accuracy"])
    assert first.metrics["macro_f1"] == pytest.approx(second.metrics["macro_f1"])


def test_quest_model_metrics_are_reproducible() -> None:
    from monetka.ml.train import train_quest_recommender

    first = train_quest_recommender()
    second = train_quest_recommender()
    assert first.metrics["spearman_rho"] == pytest.approx(second.metrics["spearman_rho"])
    assert first.metrics["mae"] == pytest.approx(second.metrics["mae"])


def test_export_parity_is_reproducible() -> None:
    """The ONNX parity result must not vary between identical exports."""
    from monetka.ml.export.onnx_export import export_quest_recommender

    first = export_quest_recommender()
    second = export_quest_recommender()
    assert first is not None and second is not None
    assert first.parity == second.parity
    assert first.size_bytes == second.size_bytes
