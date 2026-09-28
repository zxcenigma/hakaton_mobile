"""DuckDB warehouse access.

DuckDB is the engine for the ``local`` run mode: a single file, no server, and
it reads the raw JSONL partitions directly. The ``compose`` stack swaps it for
Iceberg-on-SeaweedFS queried through Trino — the SQL in ``transform/`` is written to
run on both, which is the whole point of keeping it in dbt.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from monetka.common.config import get_settings
from monetka.common.logging import get_logger

log = get_logger("warehouse")

SCHEMAS = ("bronze", "silver", "gold", "ml")


@contextmanager
def connect(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the warehouse, creating the schemas on first use."""
    settings = get_settings()
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(settings.warehouse_path), read_only=read_only)
    try:
        if not read_only:
            for schema in SCHEMAS:
                conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        yield conn
    finally:
        conn.close()


def table_exists(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return bool(row and row[0])


def row_count(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    if not table_exists(conn, schema, table):
        return 0
    row = conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()
    return int(row[0]) if row else 0


def export_parquet(schema: str, table: str, destination: Path) -> Path:
    """Materialise a table to Parquet — the handoff format for dbt, Feast and CI."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect(read_only=True) as conn:
        conn.execute(
            f"COPY (SELECT * FROM {schema}.{table}) TO '{destination.as_posix()}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    log.info("parquet_exported", table=f"{schema}.{table}", path=str(destination))
    return destination
