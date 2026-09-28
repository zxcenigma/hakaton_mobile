"""Tests for the data-quality and compliance checks.

Two halves, and both matter:

* the checks **pass on healthy data** — otherwise CI cries wolf and gets muted;
* the checks **fail on broken data** — a check that cannot fail proves nothing,
  so each invariant is deliberately violated and the check is expected to catch
  it.

The second half is the reason this file exists. It is easy to write a quality
check that silently always passes.
"""

from __future__ import annotations

import pytest

from monetka.ingestion.warehouse import connect
from monetka.quality import checks

pytestmark = pytest.mark.usefixtures("small_cohort_gold")


# ------------------------------------------------- healthy data passes ------


def test_full_report_passes_on_generated_data() -> None:
    report = checks.run_all_checks()
    failures = [f"{r.name}: {r.detail}" for r in report.failures]
    assert report.passed, f"quality failed on healthy data: {failures}"


def test_report_covers_every_registered_check() -> None:
    report = checks.run_all_checks()
    assert len(report.results) == len(checks.ALL_CHECKS)


def test_tz_content_minimums_are_met_from_observed_data() -> None:
    """ТЗ §2.6 proven from the warehouse, not from the YAML."""
    with connect(read_only=True) as conn:
        result = checks.check_content_minimums(conn)
    assert result.passed, result.detail


def test_privacy_audit_covers_the_whole_warehouse() -> None:
    with connect(read_only=True) as conn:
        result = checks.check_no_personal_data_columns(conn)
    assert result.passed
    assert "audited" in result.detail


# ------------------------------------------------- broken data is caught ----


@pytest.fixture
def scratch_table():
    """Create a disposable copy of a silver table, and always clean it up."""
    created: list[str] = []

    def _make(source: str, mutation: str) -> None:
        with connect() as conn:
            conn.execute(
                f"CREATE OR REPLACE TABLE silver.{source}_backup AS SELECT * FROM silver.{source}"
            )
            conn.execute(mutation)
        created.append(source)

    yield _make

    with connect() as conn:
        for source in created:
            conn.execute(
                f"CREATE OR REPLACE TABLE silver.{source} AS SELECT * FROM silver.{source}_backup"
            )
            conn.execute(f"DROP TABLE IF EXISTS silver.{source}_backup")


def test_broken_purchase_arithmetic_is_detected(scratch_table) -> None:
    """Coins appearing from nowhere must fail the check."""
    scratch_table(
        "fct_purchase",
        "UPDATE silver.fct_purchase SET balance_after = balance_after + 5 "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_purchase LIMIT 3)",
    )
    with connect(read_only=True) as conn:
        result = checks.check_purchase_arithmetic(conn)
    assert not result.passed
    assert "3 violations" in result.detail


def test_negative_balance_is_detected(scratch_table) -> None:
    scratch_table(
        "fct_purchase",
        "UPDATE silver.fct_purchase SET balance_after = -10 "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_purchase LIMIT 1)",
    )
    with connect(read_only=True) as conn:
        assert not checks.check_no_negative_balance(conn).passed


def test_plan_over_allocation_is_detected(scratch_table) -> None:
    scratch_table(
        "fct_budget_plan",
        "UPDATE silver.fct_budget_plan SET unallocated = -1 "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_budget_plan LIMIT 2)",
    )
    with connect(read_only=True) as conn:
        assert not checks.check_plan_never_overallocates(conn).passed


def test_stage_regression_is_detected(scratch_table) -> None:
    """ТЗ §2 — losing earned progress must be caught, not tolerated."""
    scratch_table(
        "fct_pet_stage",
        "UPDATE silver.fct_pet_stage SET stage_before = 'guide', stage_after = 'cub' "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_pet_stage LIMIT 1)",
    )
    with connect(read_only=True) as conn:
        assert not checks.check_stage_never_regresses(conn).passed


def test_pet_state_below_floor_is_detected(scratch_table) -> None:
    scratch_table(
        "fct_pet_state",
        "UPDATE silver.fct_pet_state SET value_after = 0 "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_pet_state LIMIT 1)",
    )
    with connect(read_only=True) as conn:
        assert not checks.check_pet_state_floor(conn).passed


def test_orphan_item_id_is_detected(scratch_table) -> None:
    scratch_table(
        "fct_purchase",
        "UPDATE silver.fct_purchase SET item_id = 'not_in_catalogue' "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_purchase LIMIT 1)",
    )
    with connect(read_only=True) as conn:
        result = checks.check_referential_integrity(conn)
    assert not result.passed
    assert "item_id" in result.detail


def test_period_without_a_plan_is_detected(scratch_table) -> None:
    scratch_table(
        "fct_budget_plan",
        "DELETE FROM silver.fct_budget_plan "
        "WHERE rowid IN (SELECT rowid FROM silver.fct_budget_plan LIMIT 2)",
    )
    with connect(read_only=True) as conn:
        assert not checks.check_every_period_has_a_plan(conn).passed


def test_personal_data_column_is_detected() -> None:
    """Adding a personal-data-shaped column anywhere must fail the audit."""
    with connect() as conn:
        conn.execute("CREATE OR REPLACE TABLE silver._audit_probe AS SELECT 1 AS child_name")
    try:
        with connect(read_only=True) as conn:
            result = checks.check_no_personal_data_columns(conn)
        assert not result.passed
        assert "child_name" in result.detail
    finally:
        with connect() as conn:
            conn.execute("DROP TABLE IF EXISTS silver._audit_probe")


def test_a_raising_check_is_reported_as_a_failure() -> None:
    """A check that errors must fail the report, not vanish from it."""

    def exploding_check(_conn) -> checks.CheckResult:
        raise RuntimeError("boom")

    exploding_check.__name__ = "check_exploding"
    original = checks.ALL_CHECKS
    checks.ALL_CHECKS = (*original, exploding_check)
    try:
        report = checks.run_all_checks()
        assert not report.passed
        assert any("boom" in r.detail for r in report.failures)
    finally:
        checks.ALL_CHECKS = original
