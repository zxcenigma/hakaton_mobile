"""``monetka`` — one entry point for the whole platform.

Every stage is runnable on its own (``monetka generate``, ``monetka train``, …)
and ``monetka demo`` chains them into the end-to-end run used by CI and by the
five-minute reviewer walkthrough in the README.

Imports inside commands are deliberate: the CLI must start instantly and must
not require the optional extras (Kafka, Iceberg, MLflow) just to print --help.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from monetka.common.config import get_settings
from monetka.common.logging import configure_logging, get_logger


def _force_utf8_output() -> None:
    """Make the console able to print the characters this CLI actually uses.

    On a Russian Windows install the console code page is cp1251, and Python
    picks that up for stdout. The first `✓` then raises UnicodeEncodeError and
    the command dies with a traceback instead of a result — after the work is
    already done, which is the worst possible moment.

    Found by running `monetka stack-check` on the target machine rather than in
    CI, where the encoding is always UTF-8. Reviewers run it on their own
    laptops, so the default had to stop being an assumption.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # already wrapped by something else
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") in {"utf8", "utf8mb4"}:
            continue
        # A stream that refuses to be reconfigured (pytest's capture, a detached
        # pipe) is not worth dying over — the point is to avoid a crash, not to
        # guarantee the terminal is UTF-8.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

app = typer.Typer(
    name="monetka",
    help="Data & ML platform for the «Монетка» financial-literacy app.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
log = get_logger("cli")


@app.callback()
def _root() -> None:
    configure_logging()


# ---------------------------------------------------------------- generate --


@app.command()
def generate(
    players: Annotated[int, typer.Option(help="Number of virtual players.")] = 0,
    periods: Annotated[int, typer.Option(help="Game periods per player.")] = 0,
    to_kafka: Annotated[bool, typer.Option(help="Publish to Kafka instead of files.")] = False,
    seed: Annotated[int, typer.Option(help="RNG seed; identical seed ⇒ identical data.")] = 0,
) -> None:
    """Generate synthetic telemetry for a cohort of virtual players."""
    from monetka.generator.simulator import Simulator
    from monetka.generator.sink import JsonlSink, KafkaSink

    settings = get_settings()
    settings.ensure_dirs()
    n_players = players or settings.sim_players
    n_periods = periods or settings.sim_periods
    rng_seed = seed or settings.random_seed

    simulator = Simulator(seed=rng_seed)
    start = datetime.fromisoformat(settings.sim_start_date).replace(tzinfo=UTC)

    sink = (
        KafkaSink(settings.kafka_bootstrap, settings.kafka_topic_events)
        if to_kafka
        else JsonlSink(settings.raw_dir)
    )

    console.print(
        f"[bold]Simulating[/] {n_players} players × {n_periods} periods "
        f"(seed={rng_seed}) → {'Kafka' if to_kafka else settings.raw_dir}"
    )
    written = sink.write(simulator.simulate_cohort(n_players, n_periods, start))
    sink.close()

    # Ground-truth labels live beside the data, never inside it.
    labels_path = settings.data_dir / "labels" / "archetypes.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    labels_path.write_text(json.dumps(simulator.labels, indent=2, sort_keys=True), encoding="utf-8")

    console.print(f"[green]✓[/] {written:,} events written, {len(simulator.labels):,} labels")


# ------------------------------------------------------------------ bronze --


@app.command()
def bronze(
    source: Annotated[Path | None, typer.Option(help="Raw JSONL root.")] = None,
) -> None:
    """Load raw events into the bronze table (append-only, deduplicated)."""
    from monetka.ingestion.bronze import load_bronze

    settings = get_settings()
    stats = load_bronze(source or settings.raw_dir)
    console.print(
        f"[green]✓[/] bronze: {stats.rows_in:,} read, {stats.rows_loaded:,} loaded, "
        f"{stats.duplicates:,} duplicate, {stats.rejected:,} rejected"
    )


# ------------------------------------------------------------------ silver --


@app.command()
def silver() -> None:
    """Build the silver layer: typed, deduplicated, per-event-type tables."""
    from monetka.ingestion.silver import build_silver

    counts = build_silver()
    table = Table("silver table", "rows", title="Silver layer")
    for name, rows in sorted(counts.items()):
        table.add_row(name, f"{rows:,}")
    console.print(table)


# -------------------------------------------------------------------- gold --


@app.command()
def gold() -> None:
    """Build analytical marts (the gold layer)."""
    from monetka.ingestion.gold import build_gold

    counts = build_gold()
    table = Table("mart", "rows", title="Gold layer")
    for name, rows in sorted(counts.items()):
        table.add_row(name, f"{rows:,}")
    console.print(table)


# ----------------------------------------------------------------- quality --


@app.command()
def quality(
    fail_fast: Annotated[bool, typer.Option(help="Exit non-zero on the first failure.")] = True,
) -> None:
    """Run data-quality expectations over bronze, silver and gold."""
    from monetka.quality.checks import run_all_checks

    report = run_all_checks()
    table = Table("check", "layer", "status", "detail", title="Data quality")
    for result in report.results:
        style = "green" if result.passed else "red"
        table.add_row(
            result.name,
            result.layer,
            f"[{style}]{'PASS' if result.passed else 'FAIL'}[/]",
            result.detail,
        )
    console.print(table)
    if not report.passed and fail_fast:
        raise typer.Exit(code=1)


# ------------------------------------------------------------------- train --


@app.command()
def train(
    model: Annotated[str, typer.Option(help="behaviour | quest | economy | all")] = "all",
) -> None:
    """Train models and log them to MLflow (or the local fallback store)."""
    from monetka.ml.train import train_models

    results = train_models(model)
    table = Table("model", "metric", "value", "gate", title="Training")
    for res in results:
        for metric, value in res.metrics.items():
            table.add_row(res.name, metric, f"{value:.4f}", "✓" if res.passed_gate else "✗")
    console.print(table)

    # Passing the gate is necessary but not sufficient: a challenger that clears
    # the absolute threshold while being worse than the model already serving
    # must not silently replace it.
    promotion = Table("model", "promoted", "reason", title="Promotion (champion / challenger)")
    for res in results:
        mark = "[green]yes[/]" if res.promoted else "[yellow]no[/]"
        promotion.add_row(res.name, mark, str(res.promotion.get("reason", "—")))
    console.print(promotion)

    if any(not r.passed_gate for r in results):
        console.print("[red]Quality gate failed — model not promoted.[/]")
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ export --


@app.command()
def export() -> None:
    """Export trained models to ONNX (and TFLite when the toolchain is present)."""
    from monetka.ml.export.onnx_export import export_all

    artefacts = export_all()
    table = Table("model", "format", "path", "bytes", title="On-device artefacts")
    for art in artefacts:
        table.add_row(art.model, art.fmt, str(art.path.name), f"{art.size_bytes:,}")
    console.print(table)


# ------------------------------------------------------------------- serve --


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "",
    port: Annotated[int, typer.Option()] = 0,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the inference & analytics API (OpenAPI at /docs)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "monetka.serving.api:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )


# ------------------------------------------------------------------ drift ---


@app.command()
def drift(
    reference_periods: Annotated[int, typer.Option(help="Periods used as the baseline.")] = 4,
) -> None:
    """Compare recent feature distributions against a reference window."""
    from monetka.monitoring.drift import run_drift_report

    report = run_drift_report(reference_periods=reference_periods)
    table = Table("feature", "PSI", "drifted", title="Drift report")
    for row in report.features:
        table.add_row(row.feature, f"{row.psi:.3f}", "yes" if row.drifted else "no")
    console.print(table)
    console.print(
        f"[bold]{report.drifted_count}[/] of {len(report.features)} features drifted "
        f"(threshold PSI > {report.threshold})"
    )


# ------------------------------------------------------------ stack-check --


@app.command(name="stack-check")
def stack_check() -> None:
    """Validate the container stack without starting it.

    Catches what breaks a `docker compose up` before the first build: a host
    port claimed twice, a bind mount whose source is missing, an environment
    variable with no default, a `depends_on` pointing at a renamed service.

    It cannot tell you the stack *works* — that needs a daemon. The output says
    so rather than letting a green result be over-read.
    """
    from monetka.common.config import REPO_ROOT
    from monetka.infra.stack import validate_dockerfile, validate_stack

    report = validate_stack()
    for dockerfile in sorted((REPO_ROOT / "infra" / "docker").glob("Dockerfile*")):
        report.findings.extend(validate_dockerfile(dockerfile))

    summary = Table("check", "severity", "detail", title="Stack validation")
    for finding in report.findings:
        colour = "red" if finding.is_error else "yellow"
        summary.add_row(finding.check, f"[{colour}]{finding.severity}[/]", finding.detail)

    if report.findings:
        console.print(summary)
    else:
        console.print(f"[green]✓[/] {len(report.services)} services, no structural problems found")

    budget = Table("profile", "long-running services", "estimated RAM", title="Memory budget")
    for profile, megabytes in sorted(report.memory_estimate_mb.items()):
        budget.add_row(
            profile,
            str(report.long_running_counts.get(profile, 0)),
            f"≈{megabytes / 1024:.1f} GB",
        )
    console.print(budget)

    console.print(
        "\n[dim]Static checks only. Whether the images pull, the services become "
        "healthy and interoperate needs a running daemon.[/]"
    )

    if not report.passed:
        raise typer.Exit(code=1)


# --------------------------------------------------------------- contracts --


@app.command()
def contracts(
    check: Annotated[bool, typer.Option(help="Only verify; do not rewrite files.")] = False,
) -> None:
    """Publish the event contracts as JSON Schema and Avro.

    The Pydantic models are the source of truth; these files are generated from
    them so the Android team and the schema registry read the same contract the
    warehouse enforces.
    """
    from monetka.contracts.export import diff_against_published, export_contracts

    breaking = diff_against_published()
    if breaking:
        console.print("[red]Backwards-incompatible schema changes:[/]")
        for problem in breaking:
            console.print(f"  • {problem}")
        raise typer.Exit(code=1)

    if check:
        console.print("[green]✓[/] contracts are compatible with what is published")
        return

    written = export_contracts()
    table = Table("format", "files", title="Event contracts")
    for fmt, count in sorted(written.items()):
        table.add_row(fmt, str(count))
    console.print(table)


# ----------------------------------------------------------------- monitor --


@app.command()
def monitor(
    period_from: Annotated[int, typer.Option(help="Ignore periods before this one.")] = 0,
    fail_on_unhealthy: Annotated[bool, typer.Option(help="Exit non-zero if unhealthy.")] = True,
) -> None:
    """Production health of the deployed model, and the cohort comparison.

    Operational health needs no labels and catches a broken release. The cohort
    comparison is intention-to-treat at the profile level — see
    `monitoring/performance.py` for why both of those words are load-bearing.
    """
    from monetka.monitoring.performance import run_monitoring

    report = run_monitoring(period_from=period_from)
    health = report.health

    ops = Table("metric", "value", title="Deployment health")
    ops.add_row("hints shown", f"{health.hints_total:,}")
    ops.add_row("model consults", f"{health.model_consults:,}")
    ops.add_row("consult rate", f"{health.consult_rate:.1%}")
    ops.add_row(
        "latency avg / p95",
        f"{health.avg_latency_ms:.0f} / {health.p95_latency_ms:.0f} ms"
        if health.avg_latency_ms is not None
        else "—",
    )
    ops.add_row("slow inferences", f"{health.slow_inferences:,}")
    ops.add_row("distinct hints", str(health.distinct_hints))
    ops.add_row(
        "top predicted class",
        f"{health.top_class_share:.0%}" if health.top_class_share is not None else "—",
    )
    console.print(ops)

    if report.effects:
        table = Table(
            "metric",
            "model",
            "control",
            "diff",
            "95% CI",
            "what it means",
            title="Cohort comparison (intention-to-treat, per profile)",
        )
        for effect in report.effects:
            style = "green" if effect.significant and effect.difference > 0 else ""
            table.add_row(
                effect.metric,
                f"{effect.model_mean:.4f}",
                f"{effect.rule_mean:.4f}",
                f"{effect.difference:+.4f}",
                f"[{effect.ci_low:+.4f}, {effect.ci_high:+.4f}]",
                f"[{style}]{effect.note}[/]" if style else effect.note,
            )
        console.print(table)
        console.print(
            f"[dim]n = {report.effects[0].model_profiles} model / "
            f"{report.effects[0].rule_profiles} control profiles[/]"
        )

    if health.problems:
        console.print("\n[red]Problems:[/]")
        for problem in health.problems:
            console.print(f"  • {problem}")
        if fail_on_unhealthy:
            raise typer.Exit(code=1)
    else:
        console.print("\n[green]✓[/] deployment healthy")


# -------------------------------------------------------------------- demo --


@app.command()
def demo(
    players: Annotated[int, typer.Option()] = 400,
    periods: Annotated[int, typer.Option()] = 8,
) -> None:
    """End-to-end local run: generate → bronze → silver → gold → quality → train → export.

    No containers required. This is what CI executes and what a reviewer runs
    first (ТЗ §3.2 — «локальный запуск по одной понятной процедуре»).
    """
    console.rule("[bold]1/9 generate")
    generate(players=players, periods=periods, to_kafka=False, seed=0)
    console.rule("[bold]2/9 bronze")
    bronze(source=None)
    console.rule("[bold]3/9 silver")
    silver()
    console.rule("[bold]4/9 gold")
    gold()
    console.rule("[bold]5/9 quality")
    quality(fail_fast=True)
    console.rule("[bold]6/9 train")
    train(model="all")
    console.rule("[bold]7/9 export")
    export()
    console.rule("[bold]8/9 contracts")
    contracts(check=False)
    console.rule("[bold]9/9 monitor")
    # Health only: the cohort comparison needs more profiles than the demo
    # generates to say anything, and `monitor` reports that honestly.
    monitor(period_from=0, fail_on_unhealthy=True)
    console.rule("[bold green]done")
    console.print("Start the API with:  [bold]monetka serve[/]  → http://localhost:8000/docs")


if __name__ == "__main__":
    app()
