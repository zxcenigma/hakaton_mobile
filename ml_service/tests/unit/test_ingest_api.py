"""Tests for the HTTP door into bronze.

The backend will post real events here. Everything that matters about this
endpoint is a property the caller depends on and cannot check for itself:
that a retry does not duplicate, that a bad event is set aside rather than
dropped, and that the personal-data rule applies on this path exactly as it
does on the Kafka one.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monetka.serving.api import MAX_EVENTS_PER_BATCH, app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A client whose warehouse is this test's own file."""
    from monetka.common.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MONETKA_WAREHOUSE_PATH", str(tmp_path / "w.duckdb"))
    monkeypatch.setenv("MONETKA_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings()
    settings.ensure_dirs()
    yield TestClient(app)
    get_settings.cache_clear()


def event(**overrides: Any) -> dict[str, Any]:
    record = {
        "event_id": str(uuid.uuid4()),
        "event_name": "app_opened",
        "schema_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "profile_pseudo_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "period_no": 1,
        "app_version": "1.0.0",
        "android_api_level": 33,
        "demo_mode": False,
        "payload": json.dumps({"cold_start": True, "startup_latency_ms": 120}),
    }
    record.update(overrides)
    return record


class TestIngestBatch:
    def test_a_new_event_is_accepted(self, client: TestClient) -> None:
        response = client.post("/v1/events:batch", json={"events": [event()]})
        assert response.status_code == 200
        body = response.json()
        assert (body["received"], body["accepted"], body["rejected"]) == (1, 1, 0)

    def test_the_same_event_twice_is_not_counted_twice(self, client: TestClient) -> None:
        """Idempotency is the whole reason an offline-first app can retry safely.

        The device may resend the same batch any number of times after losing
        connectivity. Without this, a week offline becomes a week of inflated
        counts in every mart downstream.
        """
        one = event()
        first = client.post("/v1/events:batch", json={"events": [one]}).json()
        second = client.post("/v1/events:batch", json={"events": [one]}).json()

        assert first["accepted"] == 1
        assert second["accepted"] == 0
        assert second["duplicates"] == 1

    def test_personal_data_is_rejected_here_too(self, client: TestClient) -> None:
        """ТЗ §3.5 applies on every path into the warehouse, not just on Kafka."""
        poisoned = event(
            payload=json.dumps({"cold_start": True, "startup_latency_ms": 5, "child_name": "Вася"})
        )
        body = client.post("/v1/events:batch", json={"events": [poisoned]}).json()

        assert body["accepted"] == 0
        assert body["rejected"] == 1
        assert body["rejections"][0]["index"] == 0

    def test_one_bad_event_does_not_discard_the_good_ones(self, client: TestClient) -> None:
        """A batch is not all-or-nothing: rejecting the batch would punish the
        sender for one malformed record and guarantee a retry loop."""
        bad = event(android_api_level=10)
        body = client.post("/v1/events:batch", json={"events": [event(), bad, event()]}).json()

        assert (body["received"], body["accepted"], body["rejected"]) == (3, 2, 1)
        assert body["rejections"][0]["index"] == 1, "позиция должна указывать на само событие"

    def test_a_rejected_event_is_kept_for_inspection(self, client: TestClient) -> None:
        """Rejected is not dropped. Someone has to be able to find out why."""
        from monetka.ingestion.warehouse import connect

        client.post("/v1/events:batch", json={"events": [event(android_api_level=10)]})
        with connect(read_only=True) as conn:
            rows = conn.execute("SELECT count(*) FROM bronze.rejected_events").fetchone()
        assert rows is not None and rows[0] == 1

    def test_the_source_is_recorded(self, client: TestClient) -> None:
        """Bronze has to say where a row came from, or an audit cannot start."""
        from monetka.ingestion.warehouse import connect

        client.post("/v1/events:batch", json={"events": [event()], "source": "backend"})
        with connect(read_only=True) as conn:
            row = conn.execute("SELECT DISTINCT _source FROM bronze.raw_events").fetchone()
        assert row is not None and row[0] == "backend"

    def test_an_empty_batch_is_refused(self, client: TestClient) -> None:
        assert client.post("/v1/events:batch", json={"events": []}).status_code == 422

    def test_an_oversized_batch_is_refused(self) -> None:
        """Refused, not queued: the insert holds the single DuckDB writer, so an
        unbounded batch would block every other write behind it.

        Checked against the request model rather than over HTTP: building 5001
        envelopes to prove a length bound is a slow way to learn nothing extra.
        """
        from pydantic import ValidationError

        from monetka.serving.api import IngestRequest

        one = event()
        IngestRequest(events=[one] * MAX_EVENTS_PER_BATCH)  # ровно предел — принимается
        with pytest.raises(ValidationError):
            IngestRequest(events=[one] * (MAX_EVENTS_PER_BATCH + 1))

    def test_a_malformed_source_is_refused(self, client: TestClient) -> None:
        """`source` lands in bronze and is read back in audits, so it is bounded
        and restricted to a safe alphabet rather than taken as given."""
        response = client.post("/v1/events:batch", json={"events": [event()], "source": "x" * 40})
        assert response.status_code == 422

    def test_an_unknown_field_is_refused(self, client: TestClient) -> None:
        """`extra="forbid"` — a typo in the caller must not be silently ignored."""
        response = client.post("/v1/events:batch", json={"events": [event()], "unexpected": True})
        assert response.status_code == 422


class TestIngestSharesTheStreamingContract:
    def test_both_paths_use_the_same_validator(self) -> None:
        """Two validators would drift, and the one that drifts starts accepting
        a field it should not."""
        import inspect

        from monetka.serving import api

        source = inspect.getsource(api.ingest_events)
        assert "_parse" in source, "HTTP-приём должен использовать тот же разбор, что и Kafka"

    def test_the_source_is_a_parameter_not_a_constant(self) -> None:
        from monetka.ingestion.stream_consumer import _parse

        signature = inspect_signature(_parse)
        assert "source" in signature and "batch" in signature


def inspect_signature(func) -> str:
    import inspect

    return str(inspect.signature(func))
