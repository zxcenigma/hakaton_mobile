"""Kafka → bronze streaming consumer.

The batch loader (`bronze.py`) reads files; this reads the topic. Both end at
the same table with the same guarantees, which is the point — the compose stack
exercises the streaming path while `monetka demo` exercises the file path, and
neither is a toy version of the other.

Delivery semantics
------------------
At-least-once, deliberately. Offsets are committed **after** the batch is
durably written, so a crash between write and commit replays the batch rather
than losing it. Duplicates are then removed by the same ``event_id`` merge the
batch loader uses. The alternative — committing first — trades a duplicate for
a permanently lost event, which is the wrong trade for a child's progress.

Anything that fails the envelope contract goes to the dead-letter topic with the
reason attached. It is never dropped and never retried in a loop: a malformed
event will still be malformed on the third attempt, and a poison message that
blocks the partition is worse than one that is set aside for inspection.
"""

from __future__ import annotations

import json
import signal
import sys
from datetime import UTC, datetime
from types import FrameType
from typing import Any

from monetka.common.config import get_settings
from monetka.common.events import EventEnvelope
from monetka.common.logging import configure_logging, get_logger
from monetka.ingestion.bronze import _ARROW_SCHEMA, _COLUMNS, BRONZE_DDL
from monetka.ingestion.warehouse import connect

log = get_logger("ingestion.stream")

#: Write to the warehouse every N messages or T seconds, whichever first.
BATCH_SIZE = 5_000
BATCH_SECONDS = 30.0

_shutdown = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    global _shutdown
    log.info("shutdown_requested", signal=signum)
    _shutdown = True


def _flush(rows: list[tuple], dead_letters: list[tuple], batch_id: str) -> int:
    """Write one batch to bronze. Returns the number of new rows."""
    import pyarrow as pa

    if not rows and not dead_letters:
        return 0

    with connect() as conn:
        conn.execute(BRONZE_DDL)
        before_row = conn.execute("SELECT count(*) FROM bronze.raw_events").fetchone()
        before = int(before_row[0]) if before_row else 0

        if rows:
            table = pa.Table.from_pylist(
                [dict(zip(_COLUMNS, row, strict=True)) for row in rows], schema=_ARROW_SCHEMA
            )
            conn.register("_stream_batch", table)
            conn.execute(
                """
                INSERT INTO bronze.raw_events
                SELECT i.* FROM (SELECT DISTINCT ON (event_id) * FROM _stream_batch) i
                LEFT JOIN bronze.raw_events b USING (event_id)
                WHERE b.event_id IS NULL
                """
            )
            conn.unregister("_stream_batch")

        if dead_letters:
            dlq = pa.Table.from_pylist(
                [
                    {
                        "rejected_at": r[0],
                        "reason": r[1],
                        "raw_line": r[2],
                        "_source": r[3],
                        "_batch_id": r[4],
                    }
                    for r in dead_letters
                ]
            )
            conn.register("_stream_dlq", dlq)
            conn.execute("INSERT INTO bronze.rejected_events SELECT * FROM _stream_dlq")
            conn.unregister("_stream_dlq")

        after_row = conn.execute("SELECT count(*) FROM bronze.raw_events").fetchone()
        after = int(after_row[0]) if after_row else 0

    return after - before


def run() -> None:  # pragma: no cover - exercised by the compose integration test
    configure_logging(force_json=True)
    settings = get_settings()
    settings.ensure_dirs()

    try:
        from confluent_kafka import Consumer, KafkaError, Producer
    except ImportError:
        log.error("confluent_kafka_missing", hint="pip install -e '.[stream]'")
        sys.exit(2)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap,
            "group.id": settings.kafka_consumer_group,
            "auto.offset.reset": "earliest",
            # Manual commit: the offset moves only once the batch is in bronze.
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300_000,
        }
    )
    dlq = Producer({"bootstrap.servers": settings.kafka_bootstrap})
    consumer.subscribe([settings.kafka_topic_events])
    log.info("consumer_started", topic=settings.kafka_topic_events)

    rows: list[tuple] = []
    dead_letters: list[tuple] = []
    last_flush = datetime.now(UTC)

    try:
        while not _shutdown:
            message = consumer.poll(timeout=1.0)
            now = datetime.now(UTC)

            if message is not None:
                if message.error():
                    if message.error().code() != KafkaError._PARTITION_EOF:
                        log.error("kafka_error", error=str(message.error()))
                else:
                    raw = message.value().decode("utf-8", errors="replace")
                    parsed = _parse(raw, now)
                    if isinstance(parsed, tuple):
                        rows.append(parsed)
                    else:
                        dead_letters.append(
                            (now, parsed, raw[:4000], f"kafka://{message.topic()}", "stream")
                        )
                        dlq.produce(
                            settings.kafka_topic_dlq,
                            value=json.dumps(
                                {"reason": parsed, "raw": raw[:8000]}, ensure_ascii=False
                            ).encode("utf-8"),
                        )

            due = len(rows) >= BATCH_SIZE or (now - last_flush).total_seconds() >= BATCH_SECONDS
            if due and (rows or dead_letters):
                batch_id = now.strftime("stream-%Y%m%dT%H%M%SZ")
                loaded = _flush(rows, dead_letters, batch_id)
                log.info(
                    "batch_flushed",
                    received=len(rows),
                    loaded=loaded,
                    duplicates=len(rows) - loaded,
                    rejected=len(dead_letters),
                )
                # Only now is it safe to advance the offset.
                consumer.commit(asynchronous=False)
                dlq.flush(10)
                rows, dead_letters = [], []
                last_flush = now
    finally:
        if rows or dead_letters:
            _flush(rows, dead_letters, "stream-final")
            consumer.commit(asynchronous=False)
        consumer.close()
        dlq.flush(10)
        log.info("consumer_stopped")


def _parse(raw: str, now: datetime) -> tuple | str:
    """Validate one message. Returns the bronze row, or a rejection reason."""
    try:
        record: dict[str, Any] = json.loads(raw)
        payload_json = record.get("payload", "{}")
        envelope = EventEnvelope.model_validate({**record, "payload": json.loads(payload_json)})
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"[:500]

    return (
        str(envelope.event_id),
        envelope.event_name.value,
        envelope.schema_version,
        envelope.occurred_at,
        envelope.ingested_at or now,
        str(envelope.profile_pseudo_id),
        str(envelope.session_id),
        envelope.period_no,
        envelope.app_version,
        envelope.android_api_level,
        envelope.demo_mode,
        payload_json,
        envelope.occurred_at.date(),
        "kafka",
        "stream",
    )


if __name__ == "__main__":
    run()
