"""Export trained models to ONNX for on-device inference.

Why ONNX and why on-device
--------------------------
The app must work without a network connection (ТЗ §3.1.5) and must not send a
child's data anywhere (ТЗ §3.5). Both constraints point the same way: inference
runs on the phone, and nothing leaves it. ONNX Runtime Mobile is the target —
it ships as an Android AAR, loads a few-hundred-kilobyte model and returns in
single-digit milliseconds on the class of device the ТЗ specifies (3 GB RAM).

The parity check is the point
-----------------------------
An exported model that quietly disagrees with the one that was validated is
worse than no model: every offline metric becomes a lie. So every export is
immediately re-loaded in ONNX Runtime and scored against the original on real
warehouse rows. If predictions diverge beyond tolerance, the export fails and
the artefact is not written. This is the concrete answer to ТЗ §3.2 — «как
контролируется корректность результата».
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# IMPORT ORDER IS LOAD-BEARING. DO NOT REORDER.
#
# `skl2onnx` must be imported before `onnxruntime`. With onnx 1.23 /
# onnxruntime 1.30 / skl2onnx 1.20 on Windows, the reverse order makes
# `to_onnx` terminate the interpreter with an access violation (exit code
# 0xC0000005) — no exception, no traceback, no message. The two packages ship
# their own copies of the protobuf runtime, and whichever loads first wins;
# loading onnxruntime's first leaves the converter calling into the wrong one.
#
# Ruff's isort rule is disabled for this file in pyproject.toml, because sorting
# these imports would "fix" the module into crashing. The order is asserted by
# tests/unit/test_drift_and_export.py::test_import_order_is_safe.
# ---------------------------------------------------------------------------
from skl2onnx import to_onnx  # isort: skip
from skl2onnx.common.data_types import FloatTensorType, StringTensorType  # isort: skip
import onnxruntime as ort  # isort: skip

from scipy.stats import spearmanr

from monetka.common.config import get_settings
from monetka.common.logging import get_logger
from monetka.ml import features as feat
from monetka.ml.registry import ModelCard, load_latest

log = get_logger("ml.export")

# --------------------------------------------------------------------------
# Parity criteria
#
# The classifier must match exactly: a label is a discrete decision, and any
# disagreement means the on-device model would show a different hint.
#
# The regressor is judged on rank correlation and decision parity rather than on
# raw value equality, because its output is only ever used to rank candidate
# quests within one period for one player. Those are properties of the decision
# the product makes; an absolute-delta bound is a property of the model's tree
# geometry and would move with the training-set size.
#
# Both models now convert essentially exactly (rank correlation 1.0, mean delta
# ~2e-08), so the thresholds are set tight. Earlier they had to be loose, and
# that turned out to be a symptom worth chasing rather than a fact of life:
# HistGradientBoosting derives its split thresholds from the training data's
# precision, so training on float64 and inferring on float32 put 4.2% of rows on
# the wrong side of a bin edge, the worst by 0.15 on a 0-1 scale. Training on
# float32 — the precision the phone actually uses — removed it entirely. If
# these gates start failing again, suspect a precision mismatch before reaching
# for the threshold.
# --------------------------------------------------------------------------
CLASS_PARITY_TOLERANCE = 0  # classification: exact label match required
PROBA_TOLERANCE = 1e-4
RANK_CORRELATION_MIN = 0.999
#: Share of per-period decisions where ONNX picks a quest at least as good as
#: sklearn's, within the conversion's own noise margin. A broken conversion — a
#: wrong feature order, a dropped encoder — makes the choice effectively random,
#: which lands near 0.1-0.3 with four to nine candidates per decision.
TOP1_AGREEMENT_MIN = 0.999
SANITY_MEAN_DELTA_MAX = 1e-3  # a healthy export measures ~2e-08

#: Absolute floor for the tie margin. The effective margin is calibrated from
#: the conversion's own measured noise (see :func:`_tie_margin`); this is only a
#: lower bound for the case where the conversion is essentially exact.
TIE_MARGIN_FLOOR = 1e-4

#: Quantile of the observed |sklearn − ONNX| delta used as the tie margin.
QUANTILE_FOR_TIE_MARGIN = 0.99


@dataclass(frozen=True, slots=True)
class Artefact:
    model: str
    fmt: str
    path: Path
    size_bytes: int
    parity: str


def _target_dir() -> Path:
    path = get_settings().api_model_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_behaviour_segment() -> Artefact | None:
    """Export the behaviour classifier and verify parity against sklearn."""
    loaded = load_latest("behaviour_segment")
    if loaded is None:
        log.warning("nothing_to_export", model="behaviour_segment")
        return None
    model, card = loaded

    frame = feat.load_behaviour_frame()
    # Keep the DataFrame for sklearn (it was fitted with feature names) and a
    # bare array for ONNX Runtime, which takes a positional tensor. Both views
    # are built from the same rows in the same column order, which is what the
    # parity check is verifying.
    sample_df = frame[list(card.feature_names)].astype(np.float32).head(512)
    sample = sample_df.to_numpy()

    onnx_model = to_onnx(
        model,
        sample_df.head(1).to_numpy(),
        # zipmap off: a plain probability tensor is far easier to read from
        # Kotlin than ONNX's map-of-label→score output.
        options={id(model): {"zipmap": False}},
        target_opset=17,
    )

    destination = _target_dir() / "behaviour_segment.onnx"
    destination.write_bytes(onnx_model.SerializeToString())

    # ---- parity ---------------------------------------------------------
    session = ort.InferenceSession(destination.read_bytes(), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    onnx_out = session.run(None, {input_name: sample})

    sk_labels = model.predict(sample_df)
    onnx_labels = np.asarray(onnx_out[0]).ravel()
    mismatches = int((sk_labels.astype(str) != onnx_labels.astype(str)).sum())

    sk_proba = model.predict_proba(sample_df)
    onnx_proba = np.asarray(onnx_out[1])
    max_proba_delta = float(np.abs(sk_proba - onnx_proba).max())

    if mismatches > CLASS_PARITY_TOLERANCE or max_proba_delta > PROBA_TOLERANCE:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"ONNX parity check failed for behaviour_segment: "
            f"{mismatches} label mismatches, max probability delta {max_proba_delta:.2e}"
        )

    _write_sidecar(destination, card)
    log.info(
        "onnx_exported",
        model="behaviour_segment",
        bytes=destination.stat().st_size,
        max_proba_delta=max_proba_delta,
    )
    return Artefact(
        "behaviour_segment",
        "onnx",
        destination,
        destination.stat().st_size,
        f"exact labels, Δp≤{max_proba_delta:.1e}",
    )


def export_quest_recommender() -> Artefact | None:
    """Export the quest scorer.

    The pipeline mixes a string column (`topic`) with numeric ones, so the ONNX
    graph takes two inputs. Keeping the one-hot encoding *inside* the graph
    rather than reimplementing it in Kotlin removes a whole class of
    train/serve skew — the encoder and the model can no longer disagree.
    """
    loaded = load_latest("quest_recommender")
    if loaded is None:
        log.warning("nothing_to_export", model="quest_recommender")
        return None
    pipeline, card = loaded

    frame = feat.load_quest_frame()
    if frame.empty:
        return None
    columns = list(card.feature_names)
    numeric = [c for c in columns if c != "topic"]
    # float32 to match how the model was trained and how the phone will call it
    # (see the note in train_quest_recommender).
    frame[numeric] = frame[numeric].fillna(0.0).astype(np.float32)
    # Keep the profile id alongside the features: top-1 agreement is measured
    # per player, because that is the grain at which a ranking decision happens.
    sample_frame = frame[["profile_pseudo_id", "period_no", *columns]].head(2_000)
    sample = sample_frame[columns]

    initial_types = [
        ("topic", StringTensorType([None, 1])),
        *[(name, FloatTensorType([None, 1])) for name in numeric],
    ]
    onnx_model = to_onnx(pipeline, initial_types=initial_types, target_opset=17)

    destination = _target_dir() / "quest_recommender.onnx"
    destination.write_bytes(onnx_model.SerializeToString())

    session = ort.InferenceSession(destination.read_bytes(), providers=["CPUExecutionProvider"])
    feed: dict[str, np.ndarray] = {
        "topic": sample[["topic"]].to_numpy().astype(object),
    }
    for name in numeric:
        feed[name] = sample[[name]].to_numpy().astype(np.float32)

    onnx_scores = np.asarray(session.run(None, feed)[0]).ravel()
    sk_scores = np.asarray(pipeline.predict(sample)).ravel()
    delta = np.abs(sk_scores - onnx_scores)

    rho = float(spearmanr(sk_scores, onnx_scores).statistic)
    mean_delta = float(delta.mean())
    tie_margin = _tie_margin(delta)
    # The decision grain is one player in one period — that is the set the
    # recommender actually chooses between. Grouping by player alone would pool
    # candidates from different periods into one artificial choice and measure
    # something the product never does.
    decision_groups = (
        sample_frame["profile_pseudo_id"].astype(str) + "|" + sample_frame["period_no"].astype(str)
    ).to_numpy()
    top1_agreement = _top1_agreement(decision_groups, sk_scores, onnx_scores, tie_margin)

    failures = []
    if rho < RANK_CORRELATION_MIN:
        failures.append(f"rank correlation {rho:.6f} < {RANK_CORRELATION_MIN}")
    if top1_agreement < TOP1_AGREEMENT_MIN:
        failures.append(
            f"decision parity {top1_agreement:.4f} < {TOP1_AGREEMENT_MIN} "
            "— ONNX would recommend a measurably worse quest"
        )
    if mean_delta > SANITY_MEAN_DELTA_MAX:
        failures.append(f"mean delta {mean_delta:.2e} > {SANITY_MEAN_DELTA_MAX:.0e}")
    if failures:
        destination.unlink(missing_ok=True)
        raise RuntimeError("ONNX parity check failed for quest_recommender: " + "; ".join(failures))

    _write_sidecar(destination, card)
    log.info(
        "onnx_exported",
        model="quest_recommender",
        bytes=destination.stat().st_size,
        rank_correlation=rho,
        top1_agreement=top1_agreement,
        tie_margin=tie_margin,
        mean_delta=mean_delta,
    )
    return Artefact(
        "quest_recommender",
        "onnx",
        destination,
        destination.stat().st_size,
        f"ρ={rho:.5f}, top-1 {top1_agreement:.2%}",
    )


def _top1_agreement(
    groups: np.ndarray, reference: np.ndarray, candidate: np.ndarray, tie_margin: float
) -> float:
    """Share of players for whom both models rank the same item first.

    This is the parity criterion that corresponds to a user-visible outcome: a
    numeric difference only matters if it changes which quest is offered.

    What is measured is *regret*, not index equality: for each player, take the
    item ONNX would pick and look up its score under the reference model. If
    that score is within ``tie_margin`` of the reference model's own best, the
    exported model recommends something just as good, and the export has not
    degraded the decision.

    Counting index equality instead would fail an export for swapping two
    candidates the model itself scores as equal — which says nothing about
    conversion fidelity and everything about how confident the model happened to
    be. Regret asks the question the product actually cares about: would the
    child be offered a worse quest?
    """
    matched = 0
    total = 0
    for group in np.unique(groups):
        mask = groups == group
        scores = reference[mask]
        if scores.size < 2:
            continue  # a single candidate is trivially the same pick

        total += 1
        onnx_choice = int(np.argmax(candidate[mask]))
        regret = float(scores.max() - scores[onnx_choice])
        if regret <= tie_margin:
            matched += 1

    return matched / total if total else 1.0


def _tie_margin(delta: np.ndarray) -> float:
    """Calibrate the tie margin from the conversion's own measured noise.

    A fixed margin is guesswork: too small and ordinary float32 rounding looks
    like a defect, too large and a real regression hides behind it. The honest
    reference point is the conversion's own error distribution — a score gap
    narrower than the noise the conversion introduces is not a decision the
    export could preserve even in principle, so it is not counted as one.

    Using the 99th percentile rather than the maximum keeps a single pathological
    row from widening the margin enough to mask genuine disagreement.
    """
    return max(TIE_MARGIN_FLOOR, float(np.quantile(delta, QUANTILE_FOR_TIE_MARGIN)))


def _write_sidecar(model_path: Path, card: ModelCard) -> None:
    """Write the metadata the Android app needs to use the model safely.

    Feature order is the critical field: ONNX takes a bare tensor, so if Kotlin
    builds the input vector in a different order than training used, the model
    still returns a confident answer — just a meaningless one. Shipping the
    order alongside the model lets the app assert on it at load time.
    """
    sidecar = model_path.with_suffix(".json")
    sidecar.write_text(
        card.to_json(),
        encoding="utf-8",
    )


def export_all() -> list[Artefact]:
    """Export every model that runs on device.

    `economy_anomaly` is intentionally absent: it is a methodologist's tool that
    runs in the warehouse, never on a child's phone.
    """
    artefacts: list[Artefact] = []
    for exporter in (export_behaviour_segment, export_quest_recommender):
        artefact = exporter()
        if artefact is not None:
            artefacts.append(artefact)
    return artefacts
