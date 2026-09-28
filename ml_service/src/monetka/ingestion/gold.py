"""Gold layer — owned by dbt.

Two steps, in this order:

1. **Regenerate seeds from the content pack.** ``content/*.yaml`` is the single
   source of truth for catalogue, quests, goals and the competency mapping. The
   seeds are derived artefacts, so they are rewritten on every run and a stale
   seed can never silently disagree with the content the app ships.
2. **Run dbt.** ``dbt seed`` → ``dbt run`` → ``dbt test``.

dbt is invoked through its Python entry point rather than a shell string so the
exit status and the structured results come back directly, and Windows quoting
stops being a variable.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

from monetka.common.config import REPO_ROOT, get_settings
from monetka.common.content import get_content
from monetka.common.logging import get_logger
from monetka.ingestion.warehouse import connect, row_count

log = get_logger("ingestion.gold")

DBT_PROJECT_DIR = REPO_ROOT / "transform" / "dbt_monetka"
DBT_PACKAGES_DIR = DBT_PROJECT_DIR / "dbt_packages"
SEEDS_DIR = DBT_PROJECT_DIR / "seeds"

GOLD_MODELS = (
    "mart_period_summary",
    "mart_player_behaviour_features",
    "mart_quest_effectiveness",
    "mart_goal_progress",
    "mart_economy_health",
    "mart_competency_coverage",
    "mart_model_performance",
)


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    log.info("seed_written", path=path.name, rows=len(rows))


def regenerate_seeds() -> None:
    """Project the YAML content pack into dbt seeds."""
    content = get_content()

    _write_csv(
        SEEDS_DIR / "seed_catalog_items.csv",
        ["item_id", "category", "price", "period_need", "is_unexpected", "child_label"],
        [
            [i.id, i.category.value, i.price, i.period_need, i.unexpected, i.child_label]
            for i in content.items
        ],
    )

    _write_csv(
        SEEDS_DIR / "seed_goals.csv",
        ["goal_id", "cost", "tier", "child_label"],
        [[g.id, g.cost, g.tier, g.child_label] for g in content.goals],
    )

    _write_csv(
        SEEDS_DIR / "seed_quests.csv",
        ["quest_id", "topic", "difficulty", "choice_count", "title"],
        [[q.id, q.topic.value, q.difficulty, len(q.choices), q.title] for q in content.quests],
    )

    # The quest → competency edge list. A quest may train several competencies,
    # so this is a proper many-to-many bridge rather than a column on the quest.
    edges: list[list[object]] = []
    for competency in content.competencies:
        for quest_id in competency.get("quests", []) or []:
            edges.append([quest_id, competency["id"], competency["statement"].strip()])
    _write_csv(
        SEEDS_DIR / "seed_quest_competency.csv",
        ["quest_id", "competency_id", "competency_statement"],
        edges,
    )


def run_dbt(*args: str) -> None:
    """Invoke dbt in a subprocess; raise on a non-zero exit code.

    A subprocess rather than ``dbtRunner().invoke`` on purpose. DuckDB permits a
    single writer per file, and dbt's adapter keeps its handle open after the
    run returns — in-process, the very next read of the warehouse fails with
    «Can't open a connection to same database». Process isolation makes the
    handle disappear when dbt exits, and it matches how dbt runs in Airflow
    anyway, so local and orchestrated behaviour stay identical.
    """
    settings = get_settings()
    env = {
        **os.environ,
        # dbt resolves the DuckDB path relative to the project dir; give it an
        # absolute one so the command works from any working directory.
        "MONETKA_WAREHOUSE_PATH": str(settings.warehouse_path.resolve()),
        "PYTHONIOENCODING": "utf-8",
    }
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        *args,
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(DBT_PROJECT_DIR),
    ]
    log.info("dbt_invoke", args=" ".join(args))
    completed = subprocess.run(command, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"dbt {' '.join(args)} failed with exit code {completed.returncode}; see output above"
        )


def ensure_dbt_packages() -> None:
    """Install dbt packages if they are not already there.

    `packages.yml` pulls in dbt_utils, and dbt refuses to compile anything at
    all when `dbt_packages/` is empty — «dbt expects 1 package(s) ... found only
    0». In a checkout the directory survives from whoever ran `dbt deps` once;
    in a fresh container it does not exist, and the pipeline died at the gold
    stage with a message about packages rather than about data.

    Making it a precondition of the build instead of a step a human remembers
    means the one documented procedure (ТЗ §3.2) works on a clean machine.
    """
    if any(DBT_PACKAGES_DIR.glob("*/")):
        return
    log.info("dbt_packages_missing", path=str(DBT_PACKAGES_DIR))
    run_dbt("deps")


def build_gold(run_tests: bool = True) -> dict[str, int]:
    """Regenerate seeds, build every gold mart, then run the dbt tests."""
    ensure_dbt_packages()
    regenerate_seeds()
    run_dbt("seed", "--full-refresh")
    run_dbt("run", "--select", "tag:gold")
    if run_tests:
        # Unqualified: this runs the source contracts (silver) as well as the
        # gold model tests. Selecting `tag:gold` would silently skip the source
        # checks, which are the ones that catch an upstream regression first.
        run_dbt("test")

    counts: dict[str, int] = {}
    with connect(read_only=True) as conn:
        for model in GOLD_MODELS:
            counts[model] = row_count(conn, "gold", model)
    return counts
