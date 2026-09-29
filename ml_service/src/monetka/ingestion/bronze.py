"""Raw events → bronze.

Bronze rules, kept deliberately boring:

* **Append-only.** Nothing is ever updated or deleted; a reload is idempotent
  because ``event_id`` is the deduplication key.
* **No business logic.** Types are cast, the payload stays an opaque JSON string.
  Anything smarter belongs in silver, where it can be tested.
* **Nothing is silently dropped.** Events that fail the envelope contract land in
  ``bronze.rejected_events`` with the reason, so a schema regression is visible
  instead of quietly shrinking the dataset.

``ingested_at`` is owned by the platform, never by the device. Live ingestion
leaves it unset and it is stamped here, at load time. A backfill file — which is
what the simulator produces, and what a re-import of an archived export looks
like — already carries the delivery timestamp from when the event was originally
received, and that value is preserved: overwriting it with "now" would erase the
real arrival latency and make every historical event look freshly delivered.

Device clocks on cheap Android hardware drift and can run backwards, so silver
orders events by ``occurred_at`` with ``ingested_at`` as the tie-breaker rather
than trusting either alone.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from monetka.common.events import EventEnvelope
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect, row_count

log = get_logger("ingestion.bronze")

#: Column order of ``bronze.raw_events``; the Arrow batch must match it exactly,
#: because the merge below inserts positionally.
_COLUMNS: tuple[str, ...] = (
    "event_id",
    "event_name",
    "schema_version",
    "occurred_at",
    "ingested_at",
    "profile_pseudo_id",
    "session_id",
    "period_no",
    "app_version",
    "android_api_level",
    "demo_mode",
    "payload",
    "event_date",
    "_source",
    "_batch_id",
)

_REJECTED_COLUMNS: tuple[str, ...] = (
    "rejected_at",
    "reason",
    "raw_line",
    "_source",
    "_batch_id",
)

_TIMESTAMP = pa.timestamp("us", tz="UTC")

#: Declared explicitly so Arrow never infers a type from the first batch —
#: inference would silently widen or narrow a column when a batch happens to
#: contain only nulls, and the insert would then fail far from the cause.
_ARROW_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_name", pa.string()),
        ("schema_version", pa.int32()),
        ("occurred_at", _TIMESTAMP),
        ("ingested_at", _TIMESTAMP),
        ("profile_pseudo_id", pa.string()),
        ("session_id", pa.string()),
        ("period_no", pa.int32()),
        ("app_version", pa.string()),
        ("android_api_level", pa.int32()),
        ("demo_mode", pa.bool_()),
        ("payload", pa.string()),
        ("event_date", pa.date32()),
        ("_source", pa.string()),
        ("_batch_id", pa.string()),
    ]
)

BRONZE_DDL = """
CREATE TABLE IF NOT EXISTS bronze.raw_events (
    event_id            UUID       NOT NULL,
    event_name          VARCHAR    NOT NULL,
    schema_version      INTEGER    NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL,
    profile_pseudo_id   UUID       NOT NULL,
    session_id          UUID       NOT NULL,
    period_no           INTEGER    NOT NULL,
    -- Nullable: an event relayed by the backend has no device behind it.
    app_version         VARCHAR,
    android_api_level   INTEGER,
    demo_mode           BOOLEAN    NOT NULL,
    payload             JSON       NOT NULL,
    event_date          DATE       NOT NULL,
    _source             VARCHAR,
    _batch_id           VARCHAR    NOT NULL
);

CREATE TABLE IF NOT EXISTS bronze.rejected_events (
    rejected_at   TIMESTAMPTZ NOT NULL,
    reason        VARCHAR     NOT NULL,
    raw_line      VARCHAR     NOT NULL,
    _source       VARCHAR,
    _batch_id     VARCHAR     NOT NULL
);
"""

#: Applied after `BRONZE_DDL`, every time, in order.
#:
#: `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so
#: editing the DDL above changes only *new* warehouses. Making `app_version`
#: nullable in the string left every existing warehouse rejecting the events it
#: was edited to accept, with `NOT NULL constraint failed` — which names the
#: column and not the reason.
#:
#: Each statement must be safe to run repeatedly: they run on every connection,
#: and failures are swallowed because most of them are «already applied».
BRONZE_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE bronze.raw_events ALTER COLUMN app_version DROP NOT NULL",
    "ALTER TABLE bronze.raw_events ALTER COLUMN android_api_level DROP NOT NULL",
)


def apply_bronze_schema(conn: object) -> None:
    """Create the bronze tables and bring an existing one up to date."""
    conn.execute(BRONZE_DDL)  # type: ignore[attr-defined]
    for statement in BRONZE_MIGRATIONS:
        # «Уже применено» и «не получилось» здесь неразличимы и одинаково не
        # важны: следующая же вставка скажет правду, а падать на старте из-за
        # повторно применённой миграции — худший из вариантов.
        with contextlib.suppress(Exception):
            conn.execute(statement)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class LoadStats:
    rows_in: int
    rows_loaded: int
    duplicates: int
    rejected: int
    batch_id: str


def load_bronze(source_root: Path) -> LoadStats:
    """Load every JSONL partition under ``source_root`` into ``bronze.raw_events``."""
    batch_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(UTC)

    files = sorted(source_root.glob("event_date=*/*.jsonl"))
    if not files:
        log.warning("no_raw_files", root=str(source_root))
        return LoadStats(0, 0, 0, 0, batch_id)

    accepted: list[tuple] = []
    rejected: list[tuple] = []
    rows_in = 0

    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rows_in += 1
                try:
                    record = json.loads(line)
                    # Re-validate the envelope: bronze accepts nothing it cannot
                    # describe. The payload itself is validated in silver.
                    payload_json = record.get("payload", "{}")
                    envelope = EventEnvelope.model_validate(
                        {**record, "payload": json.loads(payload_json)}
                    )
                except Exception as exc:
                    rejected.append(
                        (
                            now,
                            f"{type(exc).__name__}: {exc}"[:500],
                            line[:4000],
                            str(path),
                            batch_id,
                        )
                    )
                    continue

                accepted.append(
                    (
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
                        str(path),
                        batch_id,
                    )
                )

    with connect() as conn:
        apply_bronze_schema(conn)
        before = row_count(conn, "bronze", "raw_events")

        if accepted:
            # Bulk insert via a registered Arrow table rather than executemany.
            # executemany round-trips every row through the Python/C boundary —
            # at half a million events that dominated the whole pipeline's
            # runtime. Handing DuckDB one columnar batch turns minutes into
            # seconds and is the only reason this scales to a real cohort.
            incoming = pa.Table.from_pylist(
                [dict(zip(_COLUMNS, row, strict=True)) for row in accepted],
                schema=_ARROW_SCHEMA,
            )
            conn.register("_incoming", incoming)
            # Idempotent merge: an event already in bronze is never inserted twice,
            # which makes re-running the loader safe after a partial failure.
            conn.execute(
                """
                INSERT INTO bronze.raw_events
                SELECT i.* FROM (
                    SELECT DISTINCT ON (event_id) * FROM _incoming
                ) i
                LEFT JOIN bronze.raw_events b USING (event_id)
                WHERE b.event_id IS NULL
                """
            )
            conn.unregister("_incoming")

        if rejected:
            rejected_table = pa.Table.from_pylist(
                [dict(zip(_REJECTED_COLUMNS, row, strict=True)) for row in rejected]
            )
            conn.register("_rejected", rejected_table)
            conn.execute("INSERT INTO bronze.rejected_events SELECT * FROM _rejected")
            conn.unregister("_rejected")

        after = row_count(conn, "bronze", "raw_events")

    loaded = after - before
    duplicates = len(accepted) - loaded
    log.info(
        "bronze_loaded",
        files=len(files),
        rows_in=rows_in,
        loaded=loaded,
        duplicates=duplicates,
        rejected=len(rejected),
        batch_id=batch_id,
    )
    return LoadStats(rows_in, loaded, duplicates, len(rejected), batch_id)
