"""Model registry.

MLflow when it is reachable, a local file-based registry when it is not.

The fallback is not a shortcut — it is what makes ``monetka demo`` runnable on a
laptop with nothing installed, and what lets CI train and gate a model without
standing up a tracking server. Both paths write the same metadata, so a model
trained locally and one trained in the compose stack are described identically
and either can be promoted.

Every version records the data it was trained on (row counts, warehouse
fingerprint), the metrics, the gate decision and the exact feature list. That
last one matters most: an on-device model that disagrees with the warehouse
about feature order produces confident nonsense, silently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from monetka.common.config import get_settings
from monetka.common.logging import get_logger

log = get_logger("ml.registry")


@dataclass(slots=True)
class ModelCard:
    """Everything needed to reproduce, audit or roll back a model version."""

    name: str
    version: str
    created_at: str
    framework: str
    task: str
    feature_names: list[str]
    class_names: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    gates: dict[str, Any] = field(default_factory=dict)
    #: Conditions under which this model's output may be used at all. The
    #: serving layer and the Android app both read this and abstain outside the
    #: stated range, rather than trusting a prediction the model was never
    #: validated to make.
    applicability: dict[str, Any] = field(default_factory=dict)
    passed_gate: bool = False
    #: Why this version was or was not promoted to `latest`. Passing the gate is
    #: necessary but not sufficient — see :func:`decide_promotion`.
    promotion: dict[str, Any] = field(default_factory=dict)
    training_rows: int = 0
    training_profiles: int = 0
    data_fingerprint: str = ""
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, sort_keys=True)


def data_fingerprint(*parts: object) -> str:
    """Short, stable hash of the training inputs, for reproducibility claims."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8"))
    return digest.hexdigest()[:16]


def _registry_dir() -> Path:
    path = get_settings().artifacts_dir / "registry"
    path.mkdir(parents=True, exist_ok=True)
    return path


#: Metric each model is judged on when deciding whether a challenger replaces
#: the incumbent, and whether higher is better.
#:
#: `economy_anomaly` is deliberately absent. It is unsupervised: `flagged_share`
#: is how many periods it singled out, not how well it did so. Comparing two
#: versions on it would rank them by an arbitrary number, which is worse than
#: not ranking them at all — so it promotes on its gate alone.
PROMOTION_METRIC: dict[str, tuple[str, bool]] = {
    "behaviour_segment": ("macro_f1", True),
    "quest_recommender": ("spearman_rho", True),
}

#: How much worse than the incumbent a challenger may be and still be promoted.
#: Not zero: retraining on a slightly different data window moves metrics by a
#: fraction of a percent, and refusing every such model would freeze the
#: registry on whichever version happened to be trained on a lucky split.
PROMOTION_TOLERANCE = 0.01


def decide_promotion(name: str, card: ModelCard) -> dict[str, Any]:
    """Decide whether this version should become `latest`.

    Passing the quality gate is necessary but not sufficient. The gate is an
    absolute threshold — «accuracy ≥ 0.80» — and a model can clear it while
    being measurably worse than the one already serving. Promoting on the gate
    alone means every retrain is a coin flip that can silently downgrade
    production.

    So a challenger must also be no worse than the incumbent, within a
    tolerance that absorbs ordinary retraining noise.

    `economy_anomaly` is exempt: it is unsupervised, has no skill score, and its
    gate is a sanity bound rather than a measure of quality. Comparing two
    versions of it on `flagged_share` would be comparing two arbitrary numbers.
    """
    if not card.passed_gate:
        return {"promoted": False, "reason": "failed the quality gate"}

    metric_spec = PROMOTION_METRIC.get(name)
    if metric_spec is None:
        return {"promoted": True, "reason": "no promotion metric declared"}

    metric, higher_is_better = metric_spec
    if metric not in card.metrics:
        return {"promoted": True, "reason": f"metric {metric!r} not reported"}

    incumbent = load_latest(name)
    if incumbent is None:
        return {
            "promoted": True,
            "reason": "no incumbent — first passing version",
            "metric": metric,
            "challenger": card.metrics[metric],
        }

    _, incumbent_card = incumbent
    if metric not in incumbent_card.metrics:
        return {
            "promoted": True,
            "reason": f"incumbent did not report {metric!r}",
            "metric": metric,
        }

    challenger_value = card.metrics[metric]
    incumbent_value = incumbent_card.metrics[metric]
    delta = challenger_value - incumbent_value
    if not higher_is_better:
        delta = -delta

    promoted = delta >= -PROMOTION_TOLERANCE
    return {
        "promoted": promoted,
        "reason": (
            f"{metric} {challenger_value:.4f} vs incumbent {incumbent_value:.4f} "
            f"({delta:+.4f}); tolerance {PROMOTION_TOLERANCE}"
        ),
        "metric": metric,
        "challenger": challenger_value,
        "incumbent": incumbent_value,
        "incumbent_version": incumbent_card.version,
        "delta": delta,
    }


def save_model(model: object, card: ModelCard) -> Path:
    """Persist a model plus its card; return the model path."""
    directory = _registry_dir() / card.name / card.version
    directory.mkdir(parents=True, exist_ok=True)

    # Decided before writing, so the card records the decision alongside the
    # model rather than leaving it to be reconstructed from timestamps later.
    card.promotion = decide_promotion(card.name, card)

    model_path = directory / "model.joblib"
    joblib.dump(model, model_path)
    (directory / "card.json").write_text(card.to_json(), encoding="utf-8")

    # `latest` moves only for a version that passed its gate *and* is no worse
    # than the incumbent. Every version is still written to disk, so a rejected
    # challenger is auditable rather than lost.
    if card.promotion.get("promoted"):
        pointer = _registry_dir() / card.name / "latest.json"
        pointer.write_text(
            json.dumps({"version": card.version, "path": str(model_path)}, indent=2),
            encoding="utf-8",
        )

    log.info(
        "model_saved",
        model=card.name,
        version=card.version,
        passed_gate=card.passed_gate,
        promoted=card.promotion.get("promoted"),
        promotion_reason=card.promotion.get("reason"),
        path=str(model_path),
    )
    _log_to_mlflow(model, card)
    return model_path


def load_latest(name: str) -> tuple[Any, ModelCard] | None:
    # `Any` rather than a Protocol: the estimator may be a bare classifier or a
    # Pipeline, and scikit-learn ships no shared typed interface for `predict` /
    # `predict_proba`. A hand-rolled Protocol would only restate that without
    # checking anything real.
    """Load the currently promoted version of ``name``, or None when there is none."""
    pointer = _registry_dir() / name / "latest.json"
    if not pointer.exists():
        return None
    target = json.loads(pointer.read_text(encoding="utf-8"))
    model_path = Path(target["path"])
    card_path = model_path.parent / "card.json"
    if not model_path.exists() or not card_path.exists():
        log.warning("registry_pointer_dangling", model=name, path=str(model_path))
        return None
    card = ModelCard(**json.loads(card_path.read_text(encoding="utf-8")))
    return joblib.load(model_path), card


def new_version() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _log_to_mlflow(model: object, card: ModelCard) -> None:
    """Mirror the run into MLflow when a tracking server is configured.

    Failure here is logged and swallowed on purpose: tracking is observability,
    and an unreachable tracking server must never fail a training job that
    otherwise produced a valid, gated model.
    """
    settings = get_settings()
    try:
        import mlflow
    except ImportError:
        log.debug("mlflow_not_installed")
        return

    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        with mlflow.start_run(run_name=f"{card.name}-{card.version}"):
            mlflow.log_params(
                {
                    "model": card.name,
                    "task": card.task,
                    "framework": card.framework,
                    "n_features": len(card.feature_names),
                    "training_rows": card.training_rows,
                    "training_profiles": card.training_profiles,
                    "data_fingerprint": card.data_fingerprint,
                }
            )
            mlflow.log_metrics(card.metrics)
            mlflow.set_tag("passed_gate", str(card.passed_gate))
            mlflow.sklearn.log_model(model, name=card.name)
        log.info("mlflow_logged", model=card.name, uri=settings.mlflow_tracking_uri)
    except Exception as exc:
        log.warning("mlflow_unavailable", error=str(exc)[:200])
