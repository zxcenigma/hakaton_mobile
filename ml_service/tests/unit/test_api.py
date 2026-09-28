"""API contract tests.

The service must behave identically whether or not a model is loaded — that is
the whole point of the fallback design, and it is the state a device is in when
the ONNX file is missing or too old. So these tests assert on the *shape* and
the *guarantees* of each response, never on a model being present.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from monetka.serving.api import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_what_is_loaded(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["content_quests"] >= 6  # ТЗ §2.6
    assert body["content_items"] >= 8  # ТЗ §2.6
    assert isinstance(body["models_loaded"], list)


def test_metrics_endpoint_is_prometheus_formatted(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "monetka_inference" in response.text


def test_hint_always_returns_text_and_a_next_step(client: TestClient) -> None:
    """ТЗ §2.5.9 — feedback explains the consequence and offers a way forward."""
    response = client.post(
        "/v1/hint",
        json={
            "essential_coverage": 0.4,
            "plan_adherence": 0.5,
            "savings_rate": 0.0,
            "periods_completed": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"].strip()
    assert body["next_step"].strip()
    assert body["source"] in {"rule", "model"}


def test_hint_prioritises_uncovered_essentials(client: TestClient) -> None:
    """A model must not be able to talk over an unfed pet."""
    response = client.post(
        "/v1/hint",
        json={
            "essential_coverage": 0.2,
            "plan_adherence": 1.0,
            "savings_rate": 0.5,
            "periods_completed": 3,
        },
    )
    body = response.json()
    assert body["hint_id"] in {"essentials_first", "saving_but_hungry"}
    assert body["source"] == "rule"


def test_model_abstains_beyond_its_validated_horizon(client: TestClient) -> None:
    """Past the measured horizon the model must not answer at all.

    Behaviour archetypes converge as children learn, so late-period predictions
    were never validated. Abstention is the correct behaviour, and the rule
    still produces a complete hint.
    """
    response = client.post(
        "/v1/hint",
        json={
            "essential_coverage": 1.0,
            "plan_adherence": 0.95,
            "savings_rate": 0.3,
            "periods_completed": 60,
        },
    )
    body = response.json()
    assert body["segment"] == "unknown"
    assert body["source"] == "rule"
    assert body["text"].strip()


def test_hint_rejects_out_of_range_values(client: TestClient) -> None:
    response = client.post(
        "/v1/hint",
        json={
            "essential_coverage": 1.5,  # > 1.0
            "plan_adherence": 0.5,
            "savings_rate": 0.1,
            "periods_completed": 2,
        },
    )
    assert response.status_code == 422


def test_hint_rejects_unknown_fields(client: TestClient) -> None:
    """`extra="forbid"` — a typo in a field name must fail loudly, not silently."""
    response = client.post(
        "/v1/hint",
        json={
            "essential_coverage": 0.9,
            "plan_adherence": 0.9,
            "savings_rate": 0.1,
            "periods_completed": 2,
            "child_name": "Вася",
        },
    )
    assert response.status_code == 422


def test_recommendation_covers_all_three_topics(client: TestClient) -> None:
    response = client.post(
        "/v1/quests/recommend",
        json={"completed_quest_ids": [], "topic_scores": {}, "periods_completed": 8, "limit": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert {q["topic"] for q in body["quests"]} == {"budgeting", "saving", "payments"}


def test_recommendation_respects_the_difficulty_ceiling(client: TestClient) -> None:
    response = client.post(
        "/v1/quests/recommend",
        json={"completed_quest_ids": [], "topic_scores": {}, "periods_completed": 0, "limit": 3},
    )
    body = response.json()
    assert body["difficulty_ceiling"] == 1
    assert all(q["difficulty"] <= 1 for q in body["quests"])


def test_recommendation_rejects_an_unknown_topic(client: TestClient) -> None:
    response = client.post(
        "/v1/quests/recommend",
        json={"topic_scores": {"cryptocurrency": 0.5}, "periods_completed": 3},
    )
    assert response.status_code == 422


def test_manifest_lists_content_and_models(client: TestClient) -> None:
    response = client.get("/v1/content/manifest")
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["content"]["topics"]) == ["budgeting", "payments", "saving"]
    assert len(body["content"]["pet_stages"]) >= 3


def test_adult_progress_rejects_a_malformed_id(client: TestClient) -> None:
    response = client.get("/v1/adult/progress/not-a-uuid")
    assert response.status_code == 422


def test_openapi_spec_is_generated(client: TestClient) -> None:
    """ТЗ §3.2 — a server side must be described by an OpenAPI specification."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "/v1/hint" in spec["paths"]
    assert "/v1/quests/recommend" in spec["paths"]
