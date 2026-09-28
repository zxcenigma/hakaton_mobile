"""Daily pipeline DAG.

Ordering here encodes one rule: **nothing downstream runs on data that failed
its checks.** Quality sits between gold and training, not beside it, so a
regression in the warehouse cannot quietly become a regression in a model that
then ships to a child's phone.

Scheduling reflects an offline-first app. Events can arrive days after they
happened (a tablet that stayed offline), so the run does not assume the previous
day is complete: it reprocesses a trailing window and relies on the bronze merge
being idempotent. That is cheaper and far more reliable than trying to guess
when a partition is "done".
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator

#: How many days back each run reprocesses. Sized from the observed arrival
#: tail: ~2% of events land more than 72 h late, and effectively none after a
#: week (see `monetka quality` → late_arrival_within_budget).
LOOKBACK_DAYS = 7

DEFAULT_ARGS = {
    "owner": "monetka-data",
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=5),
    "email_on_failure": False,
    "depends_on_past": False,
}


@dag(
    dag_id="monetka_daily",
    description="Bronze → silver → gold → quality → train → export",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["monetka", "elt", "ml"],
    doc_md=__doc__,
)
def monetka_daily() -> None:
    start = EmptyOperator(task_id="start")

    @task
    def ingest_bronze() -> dict[str, int]:
        """Load the trailing window from raw storage into bronze.

        Idempotent by ``event_id``, so overlapping windows are free.
        """
        from monetka.common.config import get_settings
        from monetka.ingestion.bronze import load_bronze

        stats = load_bronze(get_settings().raw_dir)
        return {
            "rows_in": stats.rows_in,
            "loaded": stats.rows_loaded,
            "duplicates": stats.duplicates,
            "rejected": stats.rejected,
        }

    @task
    def check_rejections(stats: dict[str, int]) -> None:
        """Fail loudly when the rejection rate spikes.

        A handful of malformed events is normal — a released app version with a
        broken field is not, and it shows up here first.
        """
        total = max(1, stats["rows_in"])
        rate = stats["rejected"] / total
        threshold = float(Variable.get("monetka_max_rejection_rate", default_var=0.01))
        if rate > threshold:
            raise ValueError(
                f"rejection rate {rate:.2%} exceeds {threshold:.2%} "
                f"({stats['rejected']} of {total}) — check the latest app release"
            )

    @task
    def build_silver() -> dict[str, int]:
        from monetka.ingestion.silver import build_silver as _build

        return _build()

    @task
    def build_gold() -> dict[str, int]:
        from monetka.ingestion.gold import build_gold as _build

        return _build(run_tests=True)

    @task
    def run_quality() -> None:
        """Hard gate. Everything downstream is skipped if this fails."""
        from monetka.quality.checks import run_all_checks

        report = run_all_checks()
        if not report.passed:
            failures = "; ".join(f"{r.name}: {r.detail}" for r in report.failures)
            raise ValueError(f"data quality failed — {failures}")

    @task
    def train_models() -> list[str]:
        """Train and gate. A model that fails its gate is not promoted."""
        from monetka.ml.train import train_models as _train

        results = _train("all")
        failed = [r.name for r in results if not r.passed_gate]
        if failed:
            raise ValueError(f"quality gate failed for: {', '.join(failed)}")
        return [r.name for r in results]

    @task
    def export_models() -> list[str]:
        """Export to ONNX. The parity check inside will fail the task if the
        exported artefact disagrees with the validated model."""
        from monetka.ml.export.onnx_export import export_all

        return [a.model for a in export_all()]

    @task
    def drift_report() -> dict[str, int]:
        """Report, never act.

        Drift is expected here — the product is *designed* to change behaviour.
        Retraining automatically on a drifting population would let the model
        chase whatever the last content change produced, so a human reads this
        alongside `mart_economy_health` and decides.
        """
        from monetka.monitoring.drift import run_drift_report

        report = run_drift_report(reference_periods=4)
        return {"drifted": report.drifted_count, "total": len(report.features)}

    @task
    def monitor_deployed_model() -> dict[str, float]:
        """Health of the model that is actually running, from the prediction log.

        Fails the run only on a *collapse* — every prediction the same class —
        because that means the feature pipeline is broken, which is this DAG's
        business. A slow or rarely-consulted model is an alerting matter, not a
        reason to fail the nightly ELT: the data would still be correct, and
        failing here would just teach everyone to ignore the red.
        """
        from monetka.monitoring.performance import MAX_CLASS_CONCENTRATION, load_health

        health = load_health()
        if health.top_class_share is not None and health.top_class_share > MAX_CLASS_CONCENTRATION:
            raise ValueError(
                f"{health.top_class_share:.0%} of predictions are one class — "
                "the feature pipeline is almost certainly broken"
            )
        return {
            "hints": float(health.hints_total),
            "consult_rate": health.consult_rate,
            "p95_latency_ms": health.p95_latency_ms or 0.0,
        }

    finish = EmptyOperator(task_id="finish")

    # Each task function is called exactly once: calling it again would create a
    # second, independent task instance rather than referencing the first.
    stats = ingest_bronze()
    rejections_ok = check_rejections(stats)
    silver = build_silver()
    gold = build_gold()
    quality = run_quality()
    trained = train_models()
    exported = export_models()
    drift = drift_report()
    monitored = monitor_deployed_model()

    start >> stats >> rejections_ok >> silver >> gold
    gold >> quality >> trained >> exported >> finish
    # Drift and deployed-model health branch off gold: both describe the data
    # and the running model, neither gates training.
    gold >> drift >> finish
    gold >> monitored >> finish


monetka_daily()
