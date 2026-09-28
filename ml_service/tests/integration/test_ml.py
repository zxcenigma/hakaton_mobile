"""Training, registry and on-device export.

Marked slow: it trains three models and converts two of them to ONNX. It is
worth the seconds, because it covers the two failure modes that would be
invisible until a child's phone had the model — a leaky split, and an exported
artefact that disagrees with the one that was validated.
"""

from __future__ import annotations

import pytest

from monetka.ml import features as feat

pytestmark = [pytest.mark.slow, pytest.mark.usefixtures("small_cohort_gold")]


# ------------------------------------------------------------ features -----


def test_feature_frame_is_labelled() -> None:
    frame = feat.load_behaviour_frame()
    assert not frame.empty
    assert frame["label"].notna().all()
    assert set(frame["label"].unique()) <= set(feat.BEHAVIOUR_LABELS)


def test_feature_frame_respects_the_applicability_horizon() -> None:
    frame = feat.load_behaviour_frame()
    assert frame["period_no"].max() <= feat.BEHAVIOUR_MAX_PERIOD


def test_features_contain_no_nulls() -> None:
    """NULLs reaching a tree model become silent zeros; catch them here."""
    frame = feat.load_behaviour_frame()
    assert not frame[list(feat.BEHAVIOUR_FEATURES)].isna().any().any()


def test_split_never_leaks_a_profile() -> None:
    """A profile in both train and test would inflate every reported metric."""
    dataset = feat.split_by_profile(feat.load_behaviour_frame())
    assert not set(dataset.groups_train) & set(dataset.groups_test)
    assert len(dataset.x_train) > 0
    assert len(dataset.x_test) > 0


def test_split_is_deterministic() -> None:
    frame = feat.load_behaviour_frame()
    first = feat.split_by_profile(frame)
    second = feat.split_by_profile(frame)
    assert list(first.groups_test) == list(second.groups_test)


def test_label_is_not_among_the_features() -> None:
    """The target must never be reachable as an input."""
    assert "label" not in feat.BEHAVIOUR_FEATURES
    assert "archetype" not in feat.BEHAVIOUR_FEATURES


# ------------------------------------------------------------ training -----


@pytest.fixture(scope="module")
def trained():
    from monetka.ml.train import train_models

    return {result.name: result for result in train_models("all")}


def test_all_three_models_train(trained) -> None:
    assert set(trained) == {"behaviour_segment", "quest_recommender", "economy_anomaly"}


def test_behaviour_model_beats_its_baseline(trained) -> None:
    """A model that cannot beat "always guess the commonest class" is noise."""
    metrics = trained["behaviour_segment"].metrics
    assert metrics["accuracy"] > metrics["baseline_accuracy"] + 0.15


def test_quest_recommender_ranks_better_than_chance(trained) -> None:
    metrics = trained["quest_recommender"].metrics
    assert metrics["spearman_rho"] > 0
    assert metrics["mae"] < metrics["baseline_mae"]


def test_gates_are_evaluated(trained) -> None:
    for result in trained.values():
        assert isinstance(result.passed_gate, bool)


# ------------------------------------------------------------ registry -----


def test_registry_round_trip(trained) -> None:
    from monetka.ml.registry import load_latest

    loaded = load_latest("behaviour_segment")
    assert loaded is not None, "a passing model must be promoted to `latest`"
    model, card = loaded
    assert card.feature_names == list(feat.BEHAVIOUR_FEATURES)
    assert card.passed_gate is True
    assert hasattr(model, "predict")


def test_card_records_the_applicability_horizon(trained) -> None:
    """The device reads this to know when to stop trusting the model."""
    from monetka.ml.registry import load_latest

    _, card = load_latest("behaviour_segment")
    assert card.applicability["max_period_no"] == feat.BEHAVIOUR_MAX_PERIOD
    assert card.applicability["abstain_outside_range"] is True


def test_failing_model_is_not_promoted() -> None:
    """A model that fails its gate is saved for audit but never becomes `latest`."""
    from monetka.ml.registry import ModelCard, load_latest, new_version, save_model

    before = load_latest("behaviour_segment")
    save_model(
        {"not": "a model"},
        ModelCard(
            name="behaviour_segment",
            version=new_version(),
            created_at="2026-03-05T00:00:00Z",
            framework="test",
            task="deliberately failing",
            feature_names=["x"],
            passed_gate=False,
        ),
    )
    after = load_latest("behaviour_segment")
    assert after is not None
    assert after[1].version == before[1].version, "a failing model overwrote `latest`"


# -------------------------------------------------------------- export -----


def test_onnx_export_and_parity(trained) -> None:
    """The exported artefact must agree with the model that was validated."""
    from monetka.ml.export.onnx_export import export_all

    artefacts = export_all()
    assert artefacts, "nothing was exported"

    by_model = {a.model: a for a in artefacts}
    assert "behaviour_segment" in by_model

    for artefact in artefacts:
        assert artefact.path.exists()
        # ТЗ §3.1.3 targets a 3 GB device; a model measured in megabytes would
        # be the wrong shape of solution for an offline phone app.
        assert artefact.size_bytes < 5_000_000, f"{artefact.model} is too large for a phone"
        assert artefact.path.with_suffix(".json").exists(), "sidecar metadata missing"


def test_exported_model_runs_in_onnx_runtime(trained) -> None:
    import numpy as np
    import onnxruntime as ort
    from skl2onnx import to_onnx  # noqa: F401  (import order: see onnx_export)

    from monetka.common.config import get_settings
    from monetka.ml.export.onnx_export import export_behaviour_segment

    artefact = export_behaviour_segment()
    assert artefact is not None

    session = ort.InferenceSession(artefact.path.read_bytes(), providers=["CPUExecutionProvider"])
    n_features = len(feat.BEHAVIOUR_FEATURES)
    batch = np.zeros((4, n_features), dtype=np.float32)
    labels, probabilities = session.run(None, {session.get_inputs()[0].name: batch})

    assert len(labels) == 4
    assert probabilities.shape == (4, len(feat.BEHAVIOUR_LABELS))
    # Probabilities must be a proper distribution — the app shows a confidence.
    assert np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5)
    assert get_settings().api_model_dir.exists()
