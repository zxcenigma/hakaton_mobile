"""Where generated events go.

Two interchangeable backends behind one protocol:

``JsonlSink``   writes Hive-partitioned JSONL to the local filesystem. This is
                the ``local`` run mode — no containers, works in CI, and the
                files are directly queryable by DuckDB.
``KafkaSink``   publishes to the ``monetka.game.events.v1`` topic, which is how
                the ``compose`` stack feeds the lakehouse.

Both produce byte-identical event JSON, so a pipeline developed against files
behaves the same against the stream.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from monetka.common.events import EventEnvelope
from monetka.common.logging import get_logger

log = get_logger("generator.sink")


class EventSink(Protocol):
    """Minimal contract every sink implements."""

    def write(self, events: Iterable[EventEnvelope]) -> int: ...

    def close(self) -> None: ...


def _serialise(event: EventEnvelope) -> dict[str, Any]:
    """Envelope -> plain JSON dict, with the payload kept as a nested object.

    Bronze stores the payload as a JSON string rather than a struct: event types
    have divergent payload shapes, and forcing them into one wide struct would
    make every schema change a table migration. Silver unpacks per event type.
    """
    record = event.model_dump(mode="json")
    record["payload"] = json.dumps(record["payload"], ensure_ascii=False, sort_keys=True)
    return record


class JsonlSink:
    """Hive-partitioned JSONL writer: ``<root>/event_date=YYYY-MM-DD/part.jsonl``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._counts: dict[str, int] = defaultdict(int)

    def write(self, events: Iterable[EventEnvelope]) -> int:
        buckets: dict[str, list[str]] = defaultdict(list)
        total = 0
        for event in events:
            buckets[event.partition_date()].append(
                json.dumps(_serialise(event), ensure_ascii=False)
            )
            total += 1

        for partition, lines in buckets.items():
            directory = self.root / f"event_date={partition}"
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "part-0000.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            self._counts[partition] += len(lines)

        log.info("jsonl_written", events=total, partitions=len(buckets), root=str(self.root))
        return total

    def close(self) -> None:
        log.info(
            "jsonl_sink_closed", partitions=len(self._counts), events=sum(self._counts.values())
        )


class KafkaSink:
    """Publishes events to Kafka, keyed by profile so a player's events stay ordered."""

    def __init__(self, bootstrap: str, topic: str) -> None:
        try:
            from confluent_kafka import Producer
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "KafkaSink needs the 'stream' extra: pip install -e '.[stream]'"
            ) from exc

        self.topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "linger.ms": 50,
                "compression.type": "zstd",
                # At-least-once with idempotence: duplicates are possible and the
                # bronze->silver step deduplicates on event_id.
                "enable.idempotence": True,
                "acks": "all",
            }
        )
        self._failed = 0

    def _on_delivery(self, err: Any, _msg: Any) -> None:
        if err is not None:
            self._failed += 1
            log.error("kafka_delivery_failed", error=str(err))

    def write(self, events: Iterable[EventEnvelope]) -> int:
        total = 0
        for event in events:
            self._producer.produce(
                topic=self.topic,
                key=str(event.profile_pseudo_id),
                value=json.dumps(_serialise(event), ensure_ascii=False).encode("utf-8"),
                callback=self._on_delivery,
            )
            total += 1
            if total % 5_000 == 0:
                self._producer.poll(0)
        self._producer.flush(30)
        log.info("kafka_published", events=total, failed=self._failed, topic=self.topic)
        return total

    def close(self) -> None:
        self._producer.flush(30)
