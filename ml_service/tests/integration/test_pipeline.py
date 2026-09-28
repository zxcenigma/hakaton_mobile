"""End-to-end pipeline test on a small deterministic cohort.

Runs generate → bronze → silver and asserts the properties the marts and models
rely on. The gold layer needs dbt, which is exercised separately by ``make
dbt-test`` and by the CI demo job; everything up to it runs here with no
external dependency at all.
"""

from __future__ import annotations

import pytest

from monetka.ingestion.warehouse import connect, row_count

pytestmark = pytest.mark.usefixtures("small_cohort")


def _scalar(sql: str) -> int:
    with connect(read_only=True) as conn:
        row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def test_bronze_is_populated() -> None:
    with connect(read_only=True) as conn:
        assert row_count(conn, "bronze", "raw_events") > 0


def test_nothing_was_rejected() -> None:
    """The generator emits only valid events; a rejection means a contract broke."""
    with connect(read_only=True) as conn:
        assert row_count(conn, "bronze", "rejected_events") == 0


def test_bronze_load_is_idempotent() -> None:
    """Re-running the loader must not duplicate a single row.

    This is what makes the DAG's overlapping lookback window safe.
    """
    from monetka.common.config import get_settings
    from monetka.ingestion.bronze import load_bronze

    before = _scalar("SELECT count(*) FROM bronze.raw_events")
    stats = load_bronze(get_settings().raw_dir)
    after = _scalar("SELECT count(*) FROM bronze.raw_events")

    assert after == before
    assert stats.rows_loaded == 0
    assert stats.duplicates == stats.rows_in


def test_event_ids_are_unique() -> None:
    duplicates = _scalar(
        "SELECT count(*) FROM (SELECT event_id FROM bronze.raw_events "
        "GROUP BY 1 HAVING count(*) > 1)"
    )
    assert duplicates == 0


def test_silver_tables_all_built() -> None:
    from monetka.ingestion.silver import SILVER_MODELS

    with connect(read_only=True) as conn:
        for table in SILVER_MODELS:
            assert row_count(conn, "silver", table) > 0, f"silver.{table} is empty"


def test_purchase_arithmetic_holds_in_silver() -> None:
    broken = _scalar(
        "SELECT count(*) FROM silver.fct_purchase WHERE balance_before - price <> balance_after"
    )
    assert broken == 0


def test_no_negative_balances_in_silver() -> None:
    assert _scalar("SELECT count(*) FROM silver.fct_purchase WHERE balance_after < 0") == 0


def test_no_plan_over_allocates() -> None:
    assert _scalar("SELECT count(*) FROM silver.fct_budget_plan WHERE unallocated < 0") == 0


def test_plan_adherence_stays_in_range() -> None:
    out_of_range = _scalar(
        "SELECT count(*) FROM silver.fct_period WHERE plan_adherence < 0 OR plan_adherence > 1"
    )
    assert out_of_range == 0


def test_essential_coverage_stays_in_range() -> None:
    out_of_range = _scalar(
        "SELECT count(*) FROM silver.fct_period "
        "WHERE essential_coverage < 0 OR essential_coverage > 1"
    )
    assert out_of_range == 0


def test_every_profile_has_exactly_one_dimension_row() -> None:
    duplicates = _scalar(
        "SELECT count(*) FROM (SELECT profile_pseudo_id FROM silver.dim_profile "
        "GROUP BY 1 HAVING count(*) > 1)"
    )
    assert duplicates == 0


def test_referential_integrity_against_the_content_pack() -> None:
    """Every id in telemetry must exist in the shipped content."""
    from monetka.common.content import get_content

    content = get_content()
    checks = [
        ("fct_purchase", "item_id", set(content.items_by_id)),
        ("fct_quest_attempt", "quest_id", set(content.quests_by_id)),
        ("fct_savings", "goal_id", set(content.goals_by_id)),
    ]
    for table, column, valid in checks:
        values = ", ".join(f"'{v}'" for v in sorted(valid))
        orphans = _scalar(f"SELECT count(*) FROM silver.{table} WHERE {column} NOT IN ({values})")
        assert orphans == 0, f"{table}.{column} has {orphans} rows outside the content pack"


def test_silver_rebuild_is_stable() -> None:
    """Rebuilding silver from unchanged bronze must give identical counts."""
    from monetka.ingestion.silver import build_silver

    first = build_silver()
    second = build_silver()
    assert first == second


def test_no_personal_data_columns_anywhere() -> None:
    """The read-time privacy audit, run over the real warehouse (ТЗ §3.5)."""
    from monetka.common.events import personal_data_reason

    with connect(read_only=True) as conn:
        columns = conn.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns "
            "WHERE table_schema IN ('bronze', 'silver', 'gold', 'ml')"
        ).fetchall()

    offenders = [f"{s}.{t}.{c}" for s, t, c in columns if personal_data_reason(c) is not None]
    assert not offenders, f"personal-data-shaped columns found: {offenders}"
