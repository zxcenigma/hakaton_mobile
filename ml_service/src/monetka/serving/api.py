"""Inference and analytics API.

ТЗ §3.2: if a server side exists, its interface must be described by an OpenAPI
specification and it must start with one clear procedure. FastAPI generates the
spec from the same models that validate the requests, so the two cannot drift;
``make up`` is the one procedure.

What this service is *not*
--------------------------
It is not on the critical path of the game. The mandatory scenario runs entirely
on device, offline (ТЗ §3.1.5). This API exists for three things:

* a **reference implementation** of the inference the app performs locally, so
  the Kotlin side has something to verify against;
* the **adult section's** aggregate view, served from the gold layer;
* **content and model distribution** — what version of the quest pack and the
  ONNX models a device should pull.

Every endpoint that touches a model degrades to the rule-based path when the
model is missing. A 200 with `source: "rule"` is a correct response, not a
failure — that is precisely the behaviour required on a device with no model.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import numpy as np
from fastapi import FastAPI, HTTPException, Path, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from monetka import __version__
from monetka.common.config import get_settings
from monetka.common.content import get_content
from monetka.common.events import QuestTopic
from monetka.common.logging import configure_logging, get_logger
from monetka.ml.registry import load_latest
from monetka.serving.recommender import (
    PeriodSnapshot,
    Segment,
    hint_for,
    max_difficulty_for,
    recommend_quests,
)

log = get_logger("serving.api")

INFERENCE_COUNT = Counter("monetka_inference_total", "Inference requests", ["model", "source"])
INFERENCE_LATENCY = Histogram(
    "monetka_inference_latency_seconds",
    "Inference latency",
    ["model"],
    # ТЗ §3.4 requires a visual response within 1 s for local actions; the
    # on-device budget for a model is far tighter, so the buckets sit low.
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0),
)

#: Loaded once at startup. A missing model is a supported state, not an error.
_MODELS: dict[str, Any] = {}


def _load_onnx_session(name: str) -> Any | None:
    """Open the exported ONNX model — the same artefact the phone runs.

    This service calls itself a reference implementation of on-device
    inference, so it has to run the same runtime, not merely the same weights.
    That is not a purity argument, it is a measurement one: scikit-learn
    predicting a single row medians 85 ms here (DataFrame overhead plus OpenMP
    thread churn on a one-row batch), while ONNX Runtime on the identical model
    medians 0.07 ms. Serving the slow path would make every latency number this
    service reports — and every alert threshold derived from them — describe
    something no device ever does.
    """
    settings = get_settings()
    path = settings.api_model_dir / f"{name}.onnx"
    if not path.exists():
        return None
    try:
        import onnxruntime as ort

        options = ort.SessionOptions()
        # One thread, like the phone. Spinning up a pool costs more than the
        # inference for a single row.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        return ort.InferenceSession(path.read_bytes(), options, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("onnx_session_failed", model=name, error=str(exc)[:200])
        return None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    for name in ("behaviour_segment", "quest_recommender"):
        loaded = load_latest(name)
        if loaded is None:
            log.warning("model_unavailable_falling_back_to_rules", model=name)
            continue
        model, card = loaded
        session = _load_onnx_session(name)
        _MODELS[name] = {"model": model, "card": card, "session": session}
        log.info(
            "model_loaded",
            model=name,
            version=card.version,
            runtime="onnx" if session is not None else "sklearn-fallback",
        )
        if session is None:
            log.warning(
                "onnx_artefact_missing_using_sklearn",
                model=name,
                hint="run `monetka export`; sklearn is ~400x slower per row",
            )
    yield
    _MODELS.clear()


app = FastAPI(
    title="Монетка — Inference & Analytics API",
    version=__version__,
    lifespan=lifespan,
    description=(
        "Reference inference and the adult section's analytics for the «Монетка» "
        "financial-literacy app. The mandatory game loop does not depend on this "
        "service: it runs offline, on device (ТЗ §3.1.5)."
    ),
    contact={"name": "Monetka team"},
    license_info={"name": "MIT"},
)


# ---------------------------------------------------------------- schemas --


class HealthResponse(BaseModel):
    status: str
    version: str
    models_loaded: list[str]
    content_items: int
    content_quests: int


class SnapshotRequest(BaseModel):
    """The period snapshot a device sends. Deliberately free of identifiers."""

    model_config = ConfigDict(extra="forbid")

    essential_coverage: float = Field(ge=0.0, le=1.0)
    plan_adherence: float = Field(ge=0.0, le=1.0)
    savings_rate: float = Field(ge=0.0, le=1.0)
    optional_spend_share: float = Field(default=0.0, ge=0.0, le=1.0)
    rejected_purchases: int = Field(default=0, ge=0)
    withdrawals: int = Field(default=0, ge=0)
    revisions_count: int = Field(default=0, ge=0)
    purchases_essential: int = Field(default=0, ge=0)
    purchases_optional: int = Field(default=0, ge=0)
    quests_completed: int = Field(default=0, ge=0)
    quest_outcome_score: float = Field(default=0.0, ge=0.0, le=1.0)
    periods_completed: int = Field(ge=0, le=10_000)


class HintResponse(BaseModel):
    hint_id: str
    text: str
    next_step: str
    source: str = Field(description="'model' when a prediction refined the wording, else 'rule'")
    segment: str
    confidence: float | None = None
    latency_ms: float


class QuestOut(BaseModel):
    quest_id: str
    topic: str
    difficulty: int
    title: str


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_quest_ids: list[str] = Field(default_factory=list, max_length=500)
    topic_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Observed mastery per topic, 0-1. A missing topic counts as 0.",
    )
    periods_completed: int = Field(ge=0, le=10_000)
    limit: int = Field(default=3, ge=1, le=10)


class RecommendResponse(BaseModel):
    quests: list[QuestOut]
    difficulty_ceiling: int
    source: str
    latency_ms: float


class AdultProgressResponse(BaseModel):
    """Aggregate view for the protected adult section (ТЗ §2.5.12).

    No grades, no ranking, no negative assessment of the child — the ТЗ is
    explicit about that. Only what was practised and how the budget went.
    """

    profile_pseudo_id: str
    periods_played: int
    quests_attempted: int
    topics_covered: int
    avg_essential_coverage: float | None
    avg_plan_adherence: float | None
    savings_regularity: float | None
    all_topics_touched: bool


# ------------------------------------------------------------- endpoints --


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness plus a statement of what is actually loaded."""
    content = get_content()
    return HealthResponse(
        status="ok",
        version=__version__,
        models_loaded=sorted(_MODELS),
        content_items=len(content.items),
        content_quests=len(content.quests),
    )


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _predict_segment(snapshot: SnapshotRequest) -> tuple[Segment, float | None]:
    """Run the behaviour model, or report UNKNOWN so the rules take over.

    Two reasons to abstain, both returning UNKNOWN rather than a guess:

    * no model is loaded — the offline/fallback path;
    * the request is outside the model's validated range. Behaviour archetypes
      converge as children learn, so past `max_period_no` the model has no
      measured skill. Answering anyway would mean shipping a prediction nobody
      validated, and at that point the rule-based hint is the right answer.
    """
    entry = _MODELS.get("behaviour_segment")
    if entry is None:
        return Segment.UNKNOWN, None

    card = entry["card"]
    model = entry["model"]

    horizon = card.applicability.get("max_period_no")
    if horizon is not None and snapshot.periods_completed > int(horizon):
        INFERENCE_COUNT.labels("behaviour_segment", "abstain_out_of_range").inc()
        return Segment.UNKNOWN, None
    payload = snapshot.model_dump()
    # Rolling-window features are not available from a single snapshot; the
    # device supplies its own rolling values in production. Here the current
    # period stands in, and any feature the caller cannot provide is zero —
    # the same convention training used for "no activity".
    stand_ins = {
        "avg_essential_coverage_w": snapshot.essential_coverage,
        "avg_plan_adherence_w": snapshot.plan_adherence,
        "avg_savings_rate_w": snapshot.savings_rate,
        "avg_optional_share_w": snapshot.optional_spend_share,
        "spend_to_income_ratio": 1.0 - snapshot.savings_rate,
        "unallocated_share": 0.0,
        "plan_adherence_volatility": 0.0,
        "savings_regularity": 1.0 if snapshot.savings_rate > 0 else 0.0,
        "plan_adherence_delta_filled": 0.0,
    }
    # Built strictly in the card's order. ONNX takes an unnamed tensor, so a
    # vector assembled in a different order still returns a confident answer —
    # just a meaningless one. This is the single most likely way to ship a
    # silently broken model.
    row = np.array(
        [[float(payload.get(name, stand_ins.get(name, 0.0))) for name in card.feature_names]],
        dtype=np.float32,
    )

    session = entry.get("session")
    if session is not None:
        labels, probabilities = session.run(None, {session.get_inputs()[0].name: row})
        predicted = str(np.asarray(labels).ravel()[0])
        confidence = float(np.asarray(probabilities).max())
    else:
        # Fallback when no ONNX artefact was exported. Correct, just far slower;
        # a DataFrame keeps sklearn's own feature-order check active.
        import pandas as pd

        frame = pd.DataFrame(row, columns=list(card.feature_names))
        predicted = str(model.predict(frame)[0])
        confidence = float(np.max(model.predict_proba(frame)))

    try:
        return Segment(predicted), confidence
    except ValueError:
        return Segment.UNKNOWN, confidence


@app.post("/v1/hint", response_model=HintResponse, tags=["inference"])
def get_hint(snapshot: SnapshotRequest) -> HintResponse:
    """Explain what happened this period and what to try next.

    Mirrors what the app computes on device. The rules decide; the model only
    refines the wording where the rules are indifferent.
    """
    started = time.perf_counter()
    with INFERENCE_LATENCY.labels("behaviour_segment").time():
        segment, confidence = _predict_segment(snapshot)

    hint = hint_for(
        PeriodSnapshot(
            essential_coverage=snapshot.essential_coverage,
            plan_adherence=snapshot.plan_adherence,
            savings_rate=snapshot.savings_rate,
            rejected_purchases=snapshot.rejected_purchases,
            periods_completed=snapshot.periods_completed,
        ),
        segment,
    )
    INFERENCE_COUNT.labels("behaviour_segment", hint.source).inc()
    return HintResponse(
        hint_id=hint.hint_id,
        text=hint.text,
        next_step=hint.next_step,
        source=hint.source,
        segment=segment.value,
        confidence=confidence,
        latency_ms=(time.perf_counter() - started) * 1000,
    )


@app.post("/v1/quests/recommend", response_model=RecommendResponse, tags=["inference"])
def recommend(request: RecommendRequest) -> RecommendResponse:
    """Pick the next quests, respecting the age and coverage constraints."""
    started = time.perf_counter()
    content = get_content()

    topic_scores: dict[QuestTopic, float] = {}
    for raw, score in request.topic_scores.items():
        try:
            topic_scores[QuestTopic(raw)] = float(score)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"unknown topic {raw!r}") from None

    model_scores: dict[str, float] | None = None
    source = "rule"
    entry = _MODELS.get("quest_recommender")
    if entry is not None:
        import pandas as pd

        candidates = [
            q
            for q in content.quests
            if q.difficulty <= max_difficulty_for(request.periods_completed)
        ]
        if candidates:
            frame = pd.DataFrame(
                [
                    {
                        "topic": q.topic.value,
                        "difficulty": q.difficulty,
                        "avg_plan_adherence_w": 0.0,
                        "avg_essential_coverage_w": 0.0,
                        "avg_savings_rate_w": 0.0,
                        "prior_outcome_score": topic_scores.get(q.topic, 0.0),
                        "periods_completed": request.periods_completed,
                    }
                    for q in candidates
                ]
            )
            columns = list(entry["card"].feature_names)
            predictions = entry["model"].predict(frame[columns])
            model_scores = {q.id: float(p) for q, p in zip(candidates, predictions, strict=True)}
            source = "model"

    quests = recommend_quests(
        completed_quest_ids=set(request.completed_quest_ids),
        topic_scores=topic_scores,
        periods_completed=request.periods_completed,
        model_scores=model_scores,
        limit=request.limit,
        content=content,
    )
    INFERENCE_COUNT.labels("quest_recommender", source).inc()
    return RecommendResponse(
        quests=[
            QuestOut(quest_id=q.id, topic=q.topic.value, difficulty=q.difficulty, title=q.title)
            for q in quests
        ],
        difficulty_ceiling=max_difficulty_for(request.periods_completed),
        source=source,
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def _warehouse() -> Any:
    from monetka.ingestion.warehouse import connect

    return connect(read_only=True)


@app.get(
    "/v1/adult/progress/{profile_pseudo_id}",
    response_model=AdultProgressResponse,
    tags=["adult"],
)
def adult_progress(
    profile_pseudo_id: Annotated[str, Path(pattern=r"^[0-9a-fA-F-]{36}$")],
) -> AdultProgressResponse:
    """Aggregate progress for the protected adult section."""
    with _warehouse() as conn:
        row = conn.execute(
            """
            SELECT profile_pseudo_id, periods_played, quests_attempted, topics_covered,
                   avg_essential_coverage, avg_plan_adherence, savings_regularity,
                   all_topics_touched
            FROM gold.mart_competency_coverage
            WHERE profile_pseudo_id = ?
            """,
            [profile_pseudo_id],
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="profile not found")

    return AdultProgressResponse(
        profile_pseudo_id=str(row[0]),
        periods_played=int(row[1] or 0),
        quests_attempted=int(row[2] or 0),
        topics_covered=int(row[3] or 0),
        avg_essential_coverage=row[4],
        avg_plan_adherence=row[5],
        savings_regularity=row[6],
        all_topics_touched=bool(row[7]),
    )


@app.get("/v1/content/manifest", tags=["content"])
def content_manifest() -> dict[str, Any]:
    """What content and models a device should be running.

    ТЗ §2.5.14 — a new quest must be addable without reworking the app. The
    device compares this manifest against what it has and pulls the difference.
    """
    content = get_content()
    settings = get_settings()
    models = {
        name: {
            "version": entry["card"].version,
            "onnx": (settings.api_model_dir / f"{name}.onnx").exists(),
        }
        for name, entry in _MODELS.items()
    }
    return {
        "content": {
            "items": len(content.items),
            "quests": len(content.quests),
            "goals": len(content.goals),
            "topics": sorted({q.topic.value for q in content.quests}),
            "pet_stages": [s.value for s in content.pet_rules.stage_order],
        },
        "models": models,
        "platform_version": __version__,
    }
