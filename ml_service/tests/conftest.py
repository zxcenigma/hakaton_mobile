"""Shared fixtures.

Tests run against a throwaway warehouse in a temp directory, never against the
developer's `data/`. The settings singleton is cached, so it is cleared and
repopulated per session rather than mutated in place.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tmp_warehouse(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Point the whole platform at an isolated data directory for the session."""
    root = tmp_path_factory.mktemp("monetka-test")
    os.environ["MONETKA_DATA_DIR"] = str(root)
    os.environ["MONETKA_WAREHOUSE_PATH"] = str(root / "warehouse" / "test.duckdb")
    # The model registry must be isolated too. Sharing the repository's
    # `artifacts/` meant a test run could load a model trained by a previous
    # run against different data, which made parity results drift between runs.
    os.environ["MONETKA_ARTIFACTS_DIR"] = str(root / "artifacts")
    os.environ["MONETKA_API_MODEL_DIR"] = str(root / "artifacts" / "models")

    from monetka.common.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_dirs()
    yield root
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def content():
    from monetka.common.content import load_content

    return load_content()


@pytest.fixture(scope="session")
def small_cohort(tmp_warehouse: Path):
    """A deterministic 40-player cohort, materialised through to gold.

    Session-scoped because building it costs a few seconds and every pipeline
    test wants the same rows. The seed is fixed, so a failure here is always
    reproducible.
    """
    import json

    from monetka.common.config import get_settings
    from monetka.generator.simulator import Simulator
    from monetka.generator.sink import JsonlSink
    from monetka.ingestion.bronze import load_bronze
    from monetka.ingestion.silver import build_silver

    settings = get_settings()
    simulator = Simulator(seed=4242)
    sink = JsonlSink(settings.raw_dir)
    start = datetime(2026, 1, 12, tzinfo=UTC)
    # 500 players × 8 periods. The behaviour model trains on periods 3-6 only
    # (its validated horizon), so a smaller cohort leaves a few hundred rows for
    # twenty features and four classes — not enough to clear the quality gate,
    # which would make the ML tests measure sampling noise rather than the
    # pipeline. This costs about a minute once per session.
    sink.write(simulator.simulate_cohort(500, 8, start))
    sink.close()

    # Ground-truth labels live beside the data, exactly as `monetka generate`
    # writes them — training joins them from there, never from telemetry.
    labels_path = settings.data_dir / "labels" / "archetypes.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(json.dumps(simulator.labels, indent=2), encoding="utf-8")

    load_bronze(settings.raw_dir)
    build_silver()
    return simulator


@pytest.fixture(scope="session")
def small_cohort_gold(small_cohort):
    """The same cohort, materialised through the dbt gold layer.

    Separate from `small_cohort` because it costs a dbt invocation; tests that
    only need silver should not pay for it.
    """
    from monetka.ingestion.gold import build_gold

    build_gold(run_tests=False)
    return small_cohort
