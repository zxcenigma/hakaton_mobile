"""Data-quality and compliance checks.

dbt tests cover column-level contracts (uniqueness, ranges, accepted values).
This module covers the two things dbt tests are a poor fit for:

1. **Cross-table invariants of the game economy.** «Balance arithmetic always
   closes», «a growth stage never regresses», «no plan over-allocates». These
   are statements about the *product* — if one fails, the Android app has a bug
   that would let a child's coins vanish, which matters far more than a null.

2. **Compliance assertions derived from the specification.** The ТЗ §2.6 content
   minimums are verified *from observed data*, not from the YAML — proving the
   demo content is actually reachable, not merely declared. And a privacy audit
   sweeps every column name in the warehouse for anything resembling personal
   data (ТЗ §3.5).

Each check returns a row rather than raising, so one run reports every problem
instead of stopping at the first. ``monetka quality`` exits non-zero if any
check fails, which is what gates the CI pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import duckdb

from monetka.common.config import get_settings
from monetka.common.content import (
    MIN_CATALOG_ITEMS,
    MIN_GOALS,
    MIN_PET_STAGES,
    MIN_QUESTS,
    get_content,
)
from monetka.common.events import PET_COMBINATION_COUNT, personal_data_reason
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect

log = get_logger("quality")

#: ТЗ §2.6 — «не менее 9 визуально различимых комбинаций» питомца.
MIN_PET_COMBINATIONS = 9
#: ТЗ §2.6 — «не менее 5 последовательных периодов».
MIN_PERIODS = 5


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    layer: str
    passed: bool
    detail: str


@dataclass(slots=True)
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [result for result in self.results if not result.passed]


Check = Callable[[duckdb.DuckDBPyConnection], CheckResult]


def _scalar(conn: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _zero_rows(
    conn: duckdb.DuckDBPyConnection, *, name: str, layer: str, sql: str, explain: str
) -> CheckResult:
    """Pass when the query returns no rows; the row count is the violation count."""
    violations = _scalar(conn, f"SELECT count(*) FROM ({sql})")
    return CheckResult(
        name=name,
        layer=layer,
        passed=violations == 0,
        detail="ok" if violations == 0 else f"{violations:,} violations — {explain}",
    )


# --------------------------------------------------------------- bronze ----


def check_no_rejected_events(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    rejected = _scalar(conn, "SELECT count(*) FROM bronze.rejected_events")
    return CheckResult(
        "no_rejected_events",
        "bronze",
        rejected == 0,
        "ok" if rejected == 0 else f"{rejected:,} events failed the envelope contract",
    )


def check_event_id_unique(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    return _zero_rows(
        conn,
        name="event_id_unique",
        layer="bronze",
        sql="SELECT event_id FROM bronze.raw_events GROUP BY 1 HAVING count(*) > 1",
        explain="deduplication on event_id failed",
    )


def check_no_future_events(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    # Device clocks drift; a small skew is tolerated, a large one means the
    # event is untrustworthy and should not shape a mart.
    return _zero_rows(
        conn,
        name="no_far_future_events",
        layer="bronze",
        sql="""
            SELECT event_id FROM bronze.raw_events
            WHERE occurred_at > ingested_at + INTERVAL 24 HOUR
        """,
        explain="occurred_at more than 24h ahead of ingestion — device clock skew",
    )


def check_late_arrival(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    settings = get_settings()
    hours = settings.dq_max_late_event_hours
    late = _scalar(
        conn,
        f"""
        SELECT count(*) FROM bronze.raw_events
        WHERE ingested_at > occurred_at + INTERVAL {hours} HOUR
        """,
    )
    total = _scalar(conn, "SELECT count(*) FROM bronze.raw_events")
    share = late / total if total else 0.0
    # Offline-first app: events legitimately arrive days late. This is a warning
    # threshold on the *share*, not a hard ban on lateness.
    return CheckResult(
        "late_arrival_within_budget",
        "bronze",
        share <= 0.05,
        f"{late:,}/{total:,} ({share:.1%}) arrived >{hours}h late",
    )


# --------------------------------------------------------------- silver ----


def check_purchase_arithmetic(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    return _zero_rows(
        conn,
        name="purchase_balance_closes",
        layer="silver",
        sql="""
            SELECT event_id FROM silver.fct_purchase
            WHERE balance_before - price <> balance_after
        """,
        explain="coins would be created or destroyed by a purchase",
    )


def check_no_negative_balance(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    # ТЗ §2.5.6 — «Отрицательный баланс и покупка при недостатке средств
    # не допускаются».
    return _zero_rows(
        conn,
        name="no_negative_balance",
        layer="silver",
        sql="SELECT event_id FROM silver.fct_purchase WHERE balance_after < 0",
        explain="ТЗ §2.5.6 forbids a negative balance",
    )


def check_plan_never_overallocates(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    # ТЗ §2.5.5 — the app controls that the plan does not exceed the budget.
    return _zero_rows(
        conn,
        name="plan_within_budget",
        layer="silver",
        sql="SELECT event_id FROM silver.fct_budget_plan WHERE unallocated < 0",
        explain="ТЗ §2.5.5 forbids allocating more than is available",
    )


def check_stage_never_regresses(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """A growth stage may only move forward.

    ТЗ §2 forbids wiping out progress already earned in response to a mistake.
    The stage ladder is ordered, so a regression is detectable as a transition
    whose target sits earlier in the order than its source.
    """
    order = [stage.value for stage in get_content().pet_rules.stage_order]
    cases = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(order))
    return _zero_rows(
        conn,
        name="stage_never_regresses",
        layer="silver",
        sql=f"""
            SELECT event_id FROM silver.fct_pet_stage
            WHERE (CASE stage_after {cases} ELSE -1 END)
               <= (CASE stage_before {cases} ELSE -1 END)
        """,
        explain="a pet growth stage moved backwards (ТЗ §2 forbids losing progress)",
    )


def check_pet_state_floor(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """No pet state may fall below the configured floor.

    This is the «безопасная ошибка» guarantee (ТЗ §2.2) expressed as data: a bad
    decision makes the pet sad, never unrecoverable.
    """
    floor = get_content().pet_rules.floor_value
    return _zero_rows(
        conn,
        name="pet_state_above_floor",
        layer="silver",
        sql=f"SELECT event_id FROM silver.fct_pet_state WHERE value_after < {floor}",
        explain=f"a pet state dropped below the floor of {floor}",
    )


def check_referential_integrity(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """Every id in telemetry must exist in the shipped content pack."""
    content = get_content()
    problems: list[str] = []

    def orphans(table: str, column: str, valid: set[str]) -> int:
        values = ", ".join(f"'{v}'" for v in sorted(valid))
        return _scalar(
            conn,
            f"SELECT count(*) FROM silver.{table} WHERE {column} NOT IN ({values})",
        )

    for table, column, valid, label in (
        ("fct_purchase", "item_id", set(content.items_by_id), "items"),
        ("fct_quest_attempt", "quest_id", set(content.quests_by_id), "quests"),
        ("fct_savings", "goal_id", set(content.goals_by_id), "goals"),
    ):
        count = orphans(table, column, valid)
        if count:
            problems.append(f"{count} {table}.{column} not in {label}")

    return CheckResult(
        "referential_integrity",
        "silver",
        not problems,
        "ok" if not problems else "; ".join(problems),
    )


def check_every_period_has_a_plan(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    return _zero_rows(
        conn,
        name="every_period_has_a_plan",
        layer="silver",
        sql="""
            SELECT p.event_id
            FROM silver.fct_period p
            LEFT JOIN silver.fct_budget_plan b
                   ON b.profile_pseudo_id = p.profile_pseudo_id
                  AND b.period_no = p.closed_period_no
            WHERE b.event_id IS NULL
        """,
        explain="a period closed without a submitted plan (ТЗ §2.5.5)",
    )


# ------------------------------------------------- ТЗ §2.6 content minima --


def check_content_minimums(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """Prove the ТЗ §2.6 minimums from observed data, not from the YAML.

    Declaring nine pet combinations in a file is easy; showing that nine were
    actually produced and reached the warehouse is the claim that survives
    review.
    """
    observed = {
        "pet_combinations": _scalar(
            conn, "SELECT count(DISTINCT pet_combination) FROM silver.dim_profile"
        ),
        "periods": _scalar(conn, "SELECT max(period_no) FROM gold.mart_period_summary"),
        "quests": _scalar(conn, "SELECT count(DISTINCT quest_id) FROM silver.fct_quest_attempt"),
        "items": _scalar(conn, "SELECT count(DISTINCT item_id) FROM silver.fct_purchase"),
        "goals": _scalar(conn, "SELECT count(DISTINCT goal_id) FROM silver.fct_savings"),
        "stages": _scalar(conn, "SELECT count(DISTINCT stage_after) FROM silver.fct_pet_stage"),
    }
    required = {
        "pet_combinations": MIN_PET_COMBINATIONS,
        "periods": MIN_PERIODS,
        "quests": MIN_QUESTS,
        "items": MIN_CATALOG_ITEMS,
        "goals": MIN_GOALS,
        # Stage transitions observed; the first stage is the starting point and
        # produces no transition, hence one fewer.
        "stages": MIN_PET_STAGES - 1,
    }
    shortfalls = [
        f"{key}: {observed[key]} < {needed}"
        for key, needed in required.items()
        if observed[key] < needed
    ]
    detail = (
        ", ".join(f"{k}={v}" for k, v in observed.items())
        if not shortfalls
        else "; ".join(shortfalls)
    )
    return CheckResult("tz_2_6_content_minimums", "gold", not shortfalls, detail)


# -------------------------------------------------------- privacy audit ----


def check_no_personal_data_columns(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """Sweep every column name in the warehouse for personal-data patterns.

    The event contract blocks this at write time; this is the independent
    read-time audit, so a table created by hand, by dbt or by a future
    contributor is covered too (ТЗ §3.5).
    """
    rows = conn.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema IN ('bronze', 'silver', 'gold', 'ml')
        """
    ).fetchall()

    offenders = [
        f"{schema}.{table}.{column} ({reason})"
        for schema, table, column in rows
        if (reason := personal_data_reason(column)) is not None
    ]
    return CheckResult(
        "no_personal_data_columns",
        "all",
        not offenders,
        f"{len(rows)} columns audited, none personal-data-shaped"
        if not offenders
        else ", ".join(offenders[:10]),
    )


def check_pet_combination_space(conn: duckdb.DuckDBPyConnection) -> CheckResult:
    """The content pack must *offer* at least nine combinations, whatever was played."""
    return CheckResult(
        "pet_combination_space",
        "content",
        PET_COMBINATION_COUNT >= MIN_PET_COMBINATIONS,
        f"{PET_COMBINATION_COUNT} combinations available (ТЗ §2.6 requires ≥{MIN_PET_COMBINATIONS})",
    )


ALL_CHECKS: tuple[Check, ...] = (
    check_no_rejected_events,
    check_event_id_unique,
    check_no_future_events,
    check_late_arrival,
    check_purchase_arithmetic,
    check_no_negative_balance,
    check_plan_never_overallocates,
    check_stage_never_regresses,
    check_pet_state_floor,
    check_referential_integrity,
    check_every_period_has_a_plan,
    check_content_minimums,
    check_pet_combination_space,
    check_no_personal_data_columns,
)


def run_all_checks() -> QualityReport:
    """Run every check against the warehouse and return a consolidated report."""
    report = QualityReport()
    with connect(read_only=True) as conn:
        for check in ALL_CHECKS:
            try:
                result = check(conn)
            except Exception as exc:
                result = CheckResult(
                    check.__name__.removeprefix("check_"),
                    "unknown",
                    False,
                    f"check raised {type(exc).__name__}: {exc}",
                )
            report.results.append(result)
            log.info(
                "quality_check",
                check=result.name,
                layer=result.layer,
                passed=result.passed,
                detail=result.detail,
            )
    return report
