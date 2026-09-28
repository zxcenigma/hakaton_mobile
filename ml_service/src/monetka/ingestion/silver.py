"""Bronze → silver: one typed table per event family.

Silver is where the opaque bronze payload becomes columns. Three things happen
here and nowhere else:

* **Payload unpacking.** ``json_extract`` per event type, with explicit casts.
  A payload that does not match its contract yields NULLs, which the quality
  checks then catch — rather than a crash at 03:00 in an Airflow task.
* **Ordering repair.** Android device clocks drift and can run backwards, so
  every fact is sequenced with ``row_number() OVER (PARTITION BY profile
  ORDER BY occurred_at, ingested_at, event_id)``. The tie-breakers make the
  order total and therefore reproducible across re-runs.
* **Deduplication.** Kafka delivery is at-least-once; silver keeps the first
  occurrence of each ``event_id``.

Tables are rebuilt in full on every run (``CREATE OR REPLACE``). At this data
volume it costs seconds and removes a whole class of incremental-state bugs;
the incremental strategy lives in the dbt gold models where it actually pays.
"""

from __future__ import annotations

from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect, row_count

log = get_logger("ingestion.silver")

#: Common projection: bronze rows of one event type, deduplicated and sequenced.
_BASE = """
WITH deduped AS (
    SELECT *, row_number() OVER (
        PARTITION BY event_id ORDER BY ingested_at
    ) AS _rn
    FROM bronze.raw_events
    WHERE event_name = '{event}'
)
SELECT
    event_id,
    profile_pseudo_id,
    session_id,
    period_no,
    occurred_at,
    ingested_at,
    event_date,
    app_version,
    android_api_level,
    demo_mode,
    row_number() OVER (
        PARTITION BY profile_pseudo_id
        ORDER BY occurred_at, ingested_at, event_id
    ) AS seq_in_profile,
    {columns}
FROM deduped
WHERE _rn = 1
"""


def _model(event: str, columns: str) -> str:
    return _BASE.format(event=event, columns=columns)


SILVER_MODELS: dict[str, str] = {
    # --------------------------------------------------------------- dims --
    "dim_profile": """
        WITH created AS (
            SELECT
                profile_pseudo_id,
                occurred_at,
                json_extract_string(payload, '$.pet_species')    AS pet_species,
                json_extract_string(payload, '$.pet_colour')     AS pet_colour,
                json_extract_string(payload, '$.pet_accessory')  AS pet_accessory,
                CAST(json_extract(payload, '$.onboarding_seconds') AS INTEGER) AS onboarding_seconds,
                app_version,
                android_api_level,
                row_number() OVER (PARTITION BY profile_pseudo_id ORDER BY occurred_at) AS _rn
            FROM bronze.raw_events
            WHERE event_name = 'profile_created'
        ),
        activity AS (
            SELECT
                profile_pseudo_id,
                min(occurred_at) AS first_seen_at,
                max(occurred_at) AS last_seen_at,
                max(period_no)   AS last_period_no,
                count(DISTINCT session_id) AS sessions,
                bool_or(demo_mode)         AS ever_demo_mode
            FROM bronze.raw_events
            GROUP BY 1
        )
        SELECT
            a.profile_pseudo_id,
            a.first_seen_at,
            a.last_seen_at,
            a.last_period_no,
            a.sessions,
            a.ever_demo_mode,
            c.pet_species,
            c.pet_colour,
            c.pet_accessory,
            -- ТЗ §2.6: ≥9 visually distinct combinations; this is the key we
            -- count distinct values of to prove it from data, not from a claim.
            concat_ws('/', c.pet_species, c.pet_colour, c.pet_accessory) AS pet_combination,
            c.onboarding_seconds,
            c.app_version      AS first_app_version,
            c.android_api_level AS first_android_api_level
        FROM activity a
        LEFT JOIN created c
               ON c.profile_pseudo_id = a.profile_pseudo_id AND c._rn = 1
    """,
    # -------------------------------------------------------------- facts --
    "fct_app_open": _model(
        "app_opened",
        """
        CAST(json_extract(payload, '$.cold_start') AS BOOLEAN)          AS cold_start,
        CAST(json_extract(payload, '$.startup_latency_ms') AS INTEGER)  AS startup_latency_ms
        """,
    ),
    "fct_income": _model(
        "income_granted",
        """
        json_extract_string(payload, '$.source')                   AS income_source,
        CAST(json_extract(payload, '$.amount') AS INTEGER)         AS amount,
        CAST(json_extract(payload, '$.balance_after') AS INTEGER)  AS balance_after
        """,
    ),
    "fct_budget_plan": _model(
        "budget_plan_submitted",
        """
        CAST(json_extract(payload, '$.available_total')    AS INTEGER) AS available_total,
        CAST(json_extract(payload, '$.planned_essential')  AS INTEGER) AS planned_essential,
        CAST(json_extract(payload, '$.planned_optional')   AS INTEGER) AS planned_optional,
        CAST(json_extract(payload, '$.planned_savings')    AS INTEGER) AS planned_savings,
        CAST(json_extract(payload, '$.revisions_count')    AS INTEGER) AS revisions_count,
        CAST(json_extract(payload, '$.seconds_spent')      AS INTEGER) AS seconds_spent,
        CAST(json_extract(payload, '$.available_total') AS INTEGER)
          - CAST(json_extract(payload, '$.planned_essential') AS INTEGER)
          - CAST(json_extract(payload, '$.planned_optional')  AS INTEGER)
          - CAST(json_extract(payload, '$.planned_savings')   AS INTEGER) AS unallocated
        """,
    ),
    "fct_purchase": _model(
        "purchase_made",
        """
        json_extract_string(payload, '$.item_id')                    AS item_id,
        json_extract_string(payload, '$.item_category')              AS item_category,
        CAST(json_extract(payload, '$.price') AS INTEGER)            AS price,
        CAST(json_extract(payload, '$.balance_before') AS INTEGER)   AS balance_before,
        CAST(json_extract(payload, '$.balance_after') AS INTEGER)    AS balance_after
        """,
    ),
    "fct_purchase_rejected": _model(
        "purchase_rejected",
        """
        json_extract_string(payload, '$.item_id')              AS item_id,
        json_extract_string(payload, '$.item_category')        AS item_category,
        json_extract_string(payload, '$.reason')               AS reason,
        CAST(json_extract(payload, '$.price') AS INTEGER)      AS price,
        CAST(json_extract(payload, '$.balance') AS INTEGER)    AS balance,
        greatest(0, CAST(json_extract(payload, '$.price') AS INTEGER)
                  - CAST(json_extract(payload, '$.balance') AS INTEGER)) AS shortfall
        """,
    ),
    "fct_quest_attempt": _model(
        "quest_completed",
        """
        json_extract_string(payload, '$.quest_id')                AS quest_id,
        json_extract_string(payload, '$.topic')                   AS topic,
        json_extract_string(payload, '$.outcome')                 AS outcome,
        json_extract_string(payload, '$.choice_id')               AS choice_id,
        CAST(json_extract(payload, '$.difficulty') AS INTEGER)    AS difficulty,
        CAST(json_extract(payload, '$.attempts') AS INTEGER)      AS attempts,
        CAST(json_extract(payload, '$.seconds_spent') AS INTEGER) AS seconds_spent,
        CAST(json_extract(payload, '$.reward') AS INTEGER)        AS reward,
        CASE json_extract_string(payload, '$.outcome')
             WHEN 'optimal'    THEN 1.0
             WHEN 'suboptimal' THEN 0.5
             ELSE 0.0
        END AS outcome_score
        """,
    ),
    "fct_period": _model(
        "period_closed",
        """
        CAST(json_extract(payload, '$.closed_period_no')   AS INTEGER) AS closed_period_no,
        CAST(json_extract(payload, '$.available_total')    AS INTEGER) AS available_total,
        CAST(json_extract(payload, '$.planned_essential')  AS INTEGER) AS planned_essential,
        CAST(json_extract(payload, '$.planned_optional')   AS INTEGER) AS planned_optional,
        CAST(json_extract(payload, '$.planned_savings')    AS INTEGER) AS planned_savings,
        CAST(json_extract(payload, '$.actual_essential')   AS INTEGER) AS actual_essential,
        CAST(json_extract(payload, '$.actual_optional')    AS INTEGER) AS actual_optional,
        CAST(json_extract(payload, '$.actual_savings')     AS INTEGER) AS actual_savings,
        CAST(json_extract(payload, '$.essential_coverage') AS DOUBLE)  AS essential_coverage,
        CAST(json_extract(payload, '$.leftover')           AS INTEGER) AS leftover,
        -- Plain, explainable formula. The same number is shown to the child,
        -- so it must never become a learned score (ТЗ §2.2 «объяснимость»).
        CASE
          WHEN CAST(json_extract(payload, '$.planned_essential') AS INTEGER)
             + CAST(json_extract(payload, '$.planned_optional')  AS INTEGER)
             + CAST(json_extract(payload, '$.planned_savings')   AS INTEGER) = 0 THEN 0.0
          ELSE greatest(0.0, 1.0 - (
                 abs(CAST(json_extract(payload, '$.actual_essential') AS INTEGER)
                   - CAST(json_extract(payload, '$.planned_essential') AS INTEGER))
               + abs(CAST(json_extract(payload, '$.actual_optional') AS INTEGER)
                   - CAST(json_extract(payload, '$.planned_optional') AS INTEGER))
               + abs(CAST(json_extract(payload, '$.actual_savings') AS INTEGER)
                   - CAST(json_extract(payload, '$.planned_savings') AS INTEGER))
               )::DOUBLE / (
                 CAST(json_extract(payload, '$.planned_essential') AS INTEGER)
               + CAST(json_extract(payload, '$.planned_optional')  AS INTEGER)
               + CAST(json_extract(payload, '$.planned_savings')   AS INTEGER)
               ))
        END AS plan_adherence
        """,
    ),
    "fct_savings": """
        WITH deposits AS (
            SELECT
                event_id, profile_pseudo_id, session_id, period_no, occurred_at,
                ingested_at, event_date, demo_mode,
                'deposit' AS direction,
                json_extract_string(payload, '$.goal_id')                  AS goal_id,
                CAST(json_extract(payload, '$.amount') AS INTEGER)         AS amount,
                CAST(json_extract(payload, '$.savings_after') AS INTEGER)  AS savings_after,
                CAST(json_extract(payload, '$.balance_after') AS INTEGER)  AS balance_after,
                NULL::INTEGER AS eta_periods_before,
                NULL::INTEGER AS eta_periods_after
            FROM bronze.raw_events WHERE event_name = 'savings_deposited'
        ),
        withdrawals AS (
            SELECT
                event_id, profile_pseudo_id, session_id, period_no, occurred_at,
                ingested_at, event_date, demo_mode,
                'withdrawal' AS direction,
                json_extract_string(payload, '$.goal_id')                  AS goal_id,
                -CAST(json_extract(payload, '$.amount') AS INTEGER)        AS amount,
                CAST(json_extract(payload, '$.savings_after') AS INTEGER)  AS savings_after,
                CAST(json_extract(payload, '$.balance_after') AS INTEGER)  AS balance_after,
                CAST(json_extract(payload, '$.eta_periods_before') AS INTEGER) AS eta_periods_before,
                CAST(json_extract(payload, '$.eta_periods_after')  AS INTEGER) AS eta_periods_after
            FROM bronze.raw_events WHERE event_name = 'savings_withdrawn'
        )
        SELECT * FROM deposits
        UNION ALL
        SELECT * FROM withdrawals
    """,
    "fct_goal_event": """
        SELECT
            event_id, profile_pseudo_id, period_no, occurred_at, event_date, demo_mode,
            event_name AS goal_event,
            json_extract_string(payload, '$.goal_id')                   AS goal_id,
            CAST(json_extract(payload, '$.goal_cost') AS INTEGER)       AS goal_cost,
            CAST(json_extract(payload, '$.periods_taken') AS INTEGER)   AS periods_taken,
            CAST(json_extract(payload, '$.savings_at_selection') AS INTEGER) AS savings_at_selection
        FROM bronze.raw_events
        WHERE event_name IN ('goal_selected', 'goal_reached')
    """,
    "fct_pet_stage": _model(
        "pet_stage_changed",
        """
        json_extract_string(payload, '$.stage_before')                 AS stage_before,
        json_extract_string(payload, '$.stage_after')                  AS stage_after,
        json_extract_string(payload, '$.reason_code')                  AS reason_code,
        CAST(json_extract(payload, '$.periods_considered') AS INTEGER) AS periods_considered
        """,
    ),
    "fct_hint": _model(
        "hint_shown",
        """
        json_extract_string(payload, '$.hint_id')                       AS hint_id,
        json_extract_string(payload, '$.trigger')                       AS trigger_code,
        -- Randomly assigned cohort. The unit of the unbiased comparison.
        coalesce(json_extract_string(payload, '$.advisor_arm'), 'rule')  AS advisor_arm,
        json_extract_string(payload, '$.model_name')                    AS model_name,
        json_extract_string(payload, '$.model_version')                 AS model_version,
        json_extract_string(payload, '$.predicted_segment')             AS predicted_segment,
        CAST(json_extract(payload, '$.inference_latency_ms') AS INTEGER) AS inference_latency_ms,
        -- The arm a player was in. `rule` is not a degraded mode: it is the
        -- control group, and it is what every device without a model shows.
        CASE WHEN json_extract_string(payload, '$.model_name') IS NULL
             THEN 'rule' ELSE 'model' END                               AS hint_source
        """,
    ),
    "fct_pet_state": _model(
        "pet_state_changed",
        """
        json_extract_string(payload, '$.state')                     AS state_kind,
        json_extract_string(payload, '$.reason_code')               AS reason_code,
        CAST(json_extract(payload, '$.value_before') AS INTEGER)    AS value_before,
        CAST(json_extract(payload, '$.value_after') AS INTEGER)     AS value_after,
        CAST(json_extract(payload, '$.value_after') AS INTEGER)
          - CAST(json_extract(payload, '$.value_before') AS INTEGER) AS value_delta
        """,
    ),
}


def build_silver() -> dict[str, int]:
    """Rebuild every silver table. Returns row counts per table."""
    counts: dict[str, int] = {}
    with connect() as conn:
        for name, query in SILVER_MODELS.items():
            conn.execute(f"CREATE OR REPLACE TABLE silver.{name} AS {query}")
            counts[name] = row_count(conn, "silver", name)
            log.info("silver_built", table=name, rows=counts[name])
    return counts
