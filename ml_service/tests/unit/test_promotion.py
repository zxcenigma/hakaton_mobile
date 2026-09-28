"""Tests for the champion/challenger promotion policy.

The gate answers «is this model good enough in absolute terms». Promotion
answers «is it at least as good as the one already serving». Conflating the two
is how a retrain silently downgrades production: a model clears a 0.80
threshold, replaces one scoring 0.91, and nothing anywhere reports a problem.

These tests are what stop that.
"""

from __future__ import annotations

import pytest

from monetka.ml.registry import (
    PROMOTION_METRIC,
    PROMOTION_TOLERANCE,
    ModelCard,
    decide_promotion,
    new_version,
    save_model,
)


def _card(name: str, **metrics: float) -> ModelCard:
    return ModelCard(
        name=name,
        version=new_version(),
        created_at="2026-03-05T00:00:00Z",
        framework="test",
        task="test",
        feature_names=["a", "b"],
        metrics=dict(metrics),
        passed_gate=True,
    )


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry of its own for each test.

    Function-scoped rather than session-scoped on purpose: promotion is defined
    relative to whatever is already in the registry, so a test that saves a
    model changes the answer for every test after it. Sharing one directory made
    «no incumbent» pass alone and fail in the suite.
    """
    from monetka.common.config import get_settings

    monkeypatch.setenv("MONETKA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MONETKA_API_MODEL_DIR", str(tmp_path / "artifacts" / "models"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ----------------------------------------------------- gate is necessary ---


def test_a_model_failing_its_gate_is_never_promoted(registry) -> None:
    card = _card("behaviour_segment", macro_f1=0.99)
    card.passed_gate = False
    decision = decide_promotion("behaviour_segment", card)
    assert decision["promoted"] is False
    assert "gate" in decision["reason"]


# --------------------------------------------- but not sufficient ----------


def test_first_passing_version_is_promoted(registry) -> None:
    decision = decide_promotion("behaviour_segment", _card("behaviour_segment", macro_f1=0.80))
    assert decision["promoted"] is True
    assert "no incumbent" in decision["reason"]


def test_a_clearly_worse_challenger_is_rejected(registry) -> None:
    """The case the whole policy exists for."""
    save_model({"m": 1}, _card("behaviour_segment", macro_f1=0.91))
    decision = decide_promotion("behaviour_segment", _card("behaviour_segment", macro_f1=0.82))
    assert decision["promoted"] is False
    assert decision["incumbent"] == pytest.approx(0.91)
    assert decision["delta"] < 0


def test_a_better_challenger_is_promoted(registry) -> None:
    save_model({"m": 1}, _card("behaviour_segment", macro_f1=0.82))
    decision = decide_promotion("behaviour_segment", _card("behaviour_segment", macro_f1=0.90))
    assert decision["promoted"] is True
    assert decision["delta"] > 0


def test_noise_sized_regression_is_tolerated(registry) -> None:
    """Retraining on a shifted window moves metrics by a fraction of a percent.

    Refusing every such model would freeze the registry on whichever version
    happened to get a lucky split.
    """
    save_model({"m": 1}, _card("behaviour_segment", macro_f1=0.9000))
    challenger = _card("behaviour_segment", macro_f1=0.9000 - PROMOTION_TOLERANCE / 2)
    assert decide_promotion("behaviour_segment", challenger)["promoted"] is True


def test_regression_beyond_tolerance_is_rejected(registry) -> None:
    save_model({"m": 1}, _card("behaviour_segment", macro_f1=0.9000))
    challenger = _card("behaviour_segment", macro_f1=0.9000 - PROMOTION_TOLERANCE * 2)
    assert decide_promotion("behaviour_segment", challenger)["promoted"] is False


# --------------------------------------------------- pointer behaviour -----


def test_latest_does_not_move_for_a_rejected_challenger(registry) -> None:
    from monetka.ml.registry import load_latest

    champion = _card("behaviour_segment", macro_f1=0.91)
    save_model({"m": "champion"}, champion)

    save_model({"m": "challenger"}, _card("behaviour_segment", macro_f1=0.70))

    loaded = load_latest("behaviour_segment")
    assert loaded is not None
    assert loaded[1].version == champion.version, "a worse model took over `latest`"


def test_a_rejected_challenger_is_still_written(registry) -> None:
    """Rejected versions stay on disk so the decision is auditable."""

    save_model({"m": "champion"}, _card("behaviour_segment", macro_f1=0.91))
    challenger = _card("behaviour_segment", macro_f1=0.60)
    path = save_model({"m": "challenger"}, challenger)

    assert path.exists()
    card_path = path.parent / "card.json"
    assert card_path.exists()
    assert challenger.version in str(path)


def test_the_decision_is_recorded_on_the_card(registry) -> None:
    save_model({"m": 1}, _card("behaviour_segment", macro_f1=0.91))
    challenger = _card("behaviour_segment", macro_f1=0.70)
    save_model({"m": 2}, challenger)

    assert challenger.promotion["promoted"] is False
    assert "incumbent" in challenger.promotion


# -------------------------------------------------------- exemptions -------


def test_unsupervised_model_promotes_on_its_gate_alone(registry) -> None:
    """`flagged_share` counts what the detector singled out, not how well.

    Ranking two versions by it would be ranking them by an arbitrary number.
    """
    assert "economy_anomaly" not in PROMOTION_METRIC

    save_model({"m": 1}, _card("economy_anomaly", flagged_share=0.20))
    decision = decide_promotion("economy_anomaly", _card("economy_anomaly", flagged_share=0.05))
    assert decision["promoted"] is True
    assert "no promotion metric" in decision["reason"]


def test_missing_metric_does_not_block_promotion(registry) -> None:
    decision = decide_promotion("behaviour_segment", _card("behaviour_segment", accuracy=0.9))
    assert decision["promoted"] is True
    assert "not reported" in decision["reason"]


def test_every_declared_metric_has_a_direction() -> None:
    for name, (metric, higher_is_better) in PROMOTION_METRIC.items():
        assert isinstance(metric, str) and metric
        assert isinstance(higher_is_better, bool), f"{name}: direction must be explicit"
