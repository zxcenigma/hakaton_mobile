"""Centralised, environment-driven configuration.

Every component reads its settings from here so that the same code runs
unchanged in three modes:

* ``local``   — no containers at all; DuckDB file + local filesystem.
* ``compose`` — the full stack from ``docker-compose.yml``.
* ``ci``      — GitHub Actions; local mode plus stricter failure thresholds.

Secrets are never hard-coded: ``.env.template`` documents every key, ``.env`` is
git-ignored, and the repository is checked for leaked credentials by a
``detect-secrets`` pre-commit hook (ТЗ §3.4 — «в репозитории отсутствуют пароли,
токены, закрытые ключи подписи»).

Laid out to match ``backend/monoapi/core/_settings.py``: the service directory
and env-file location are module constants, one shared ``MODEL_CONFIG`` says
where the ``.env`` is, and a module-level ``settings`` singleton is importable
directly. Two deliberate differences from the backend, both worth stating:

* **Every variable keeps the ``MONETKA_`` prefix.** The backend reads flat names
  (``PG_HOST``, ``SERVER_PORT``). Those are exactly the names an orchestrator or
  a shared compose file is most likely to set for something else, and a silent
  collision here would repoint the warehouse or the object store without an
  error. Dropping the prefix is a one-line change in ``MODEL_CONFIG`` if the
  services ever share a single ``.env``.
* **The settings groups are flat, not nested models.** Nesting would read
  better, but it renames every access path (``settings.trino_host`` becomes
  ``settings.lakehouse.trino_host``) across the whole package for no behavioural
  gain. The section comments carry the grouping instead.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_repo_root() -> Path:
    """Find the directory that owns `data/` and `artifacts/`.

    In a checkout, this file is `<root>/src/monetka/common/config.py`, so the
    root is three levels up. Once the package is *installed* — which is exactly
    what the Docker image does — the same arithmetic lands on
    `/opt/venv/lib/python3.12`, and every default path points inside
    site-packages. The container runs as uid 999 and cannot write there, so the
    API died during startup with `PermissionError: /opt/venv/lib/python3.12/
    artifacts`. Nothing in the test suite could catch it: the tests always run
    from a checkout, where the arithmetic is right.

    So the guess is verified instead of trusted. `pyproject.toml` is the marker;
    the image copies it next to the working directory for this reason.
    """
    guess = Path(__file__).resolve().parents[3]
    if (guess / "pyproject.toml").exists():
        return guess
    # Installed, not checked out. The working directory is the only thing the
    # deployment actually controls, and it is where the volumes are mounted.
    return Path.cwd()


#: The `ml_service/` directory. Named `REPO_ROOT` for historical reasons — this
#: was a standalone repository before it moved in beside the backend and the
#: mobile app — and aliased below to the name that now describes it.
REPO_ROOT = _detect_repo_root()
ML_SERVICE_DIR = REPO_ROOT

#: One `.env`, at the root of this service, next to `.env.template`. The backend
#: keeps its own; neither service reads the other's.
ENV_FILE = (ML_SERVICE_DIR / ".env").resolve()

MODEL_CONFIG: SettingsConfigDict = SettingsConfigDict(
    env_file=ENV_FILE,
    env_file_encoding="utf-8",
    env_prefix="MONETKA_",
    extra="ignore",
)


class RunMode(StrEnum):
    LOCAL = "local"
    COMPOSE = "compose"
    CI = "ci"


class Settings(BaseSettings):
    """Platform-wide settings. Override any field via environment variables."""

    model_config = MODEL_CONFIG

    # ------------------------------------------------------------- general --
    run_mode: RunMode = RunMode.LOCAL
    env: str = "dev"
    log_level: str = "INFO"
    random_seed: int = 20260305  # date of the competency-framework protocol

    # ------------------------------------------------------------ storage ---
    data_dir: Path = REPO_ROOT / "data"
    warehouse_path: Path = REPO_ROOT / "data" / "warehouse" / "monetka.duckdb"

    #: Where trained models and exported artefacts live. A real setting rather
    #: than a path derived from the repository root: tests must be able to point
    #: it somewhere isolated. When it was hard-wired to the repo, a test run
    #: loaded models left behind by a previous run and the results moved between
    #: runs for no visible reason.
    artifacts_dir: Path = REPO_ROOT / "artifacts"

    # object storage (SeaweedFS in compose, unused in local mode)
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "monetkalocal"
    s3_secret_key: str = Field(default="monetkalocal", repr=False)
    s3_bucket_bronze: str = "monetka-bronze"
    s3_bucket_silver: str = "monetka-silver"
    s3_bucket_gold: str = "monetka-gold"
    s3_region: str = "us-east-1"

    # ------------------------------------------------------------- stream ---
    kafka_bootstrap: str = "localhost:19092"
    kafka_topic_events: str = "monetka.game.events.v1"
    kafka_topic_dlq: str = "monetka.game.events.dlq.v1"
    kafka_consumer_group: str = "monetka-bronze-ingestor"
    schema_registry_url: str = "http://localhost:18081"

    # ----------------------------------------------------------- lakehouse --
    iceberg_catalog_uri: str = "http://localhost:8181"
    iceberg_warehouse: str = "s3://monetka-bronze/warehouse"
    trino_host: str = "localhost"
    trino_port: int = 8080

    # -------------------------------------------------------------- mlops ---
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment: str = "monetka"
    model_registry_stage: str = "Production"

    # ------------------------------------------------------------ serving ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    #: Left as its own setting so a deployment can serve models from a mounted
    #: volume that is not the build's artefact directory.
    api_model_dir: Path = REPO_ROOT / "artifacts" / "models"

    # ---------------------------------------------------------- generator ---
    sim_players: int = 2_000
    sim_periods: int = 12
    sim_start_date: str = "2026-01-12"

    # --------------------------------------------------- quality gates -----
    dq_max_null_fraction: float = 0.0
    dq_max_late_event_hours: int = 72
    drift_psi_threshold: float = 0.2
    min_model_accuracy: float = 0.80

    # ----------------------------------------------------------- computed ---
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_local(self) -> bool:
        return self.run_mode in (RunMode.LOCAL, RunMode.CI)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bronze_dir(self) -> Path:
        return self.data_dir / "bronze"

    def ensure_dirs(self) -> None:
        """Create every local directory the platform writes to."""
        for path in (
            self.data_dir,
            self.raw_dir,
            self.bronze_dir,
            self.warehouse_path.parent,
            self.artifacts_dir,
            self.api_model_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton so that every module sees identical config.

    Prefer this to the `settings` object below inside library code: the cache
    can be cleared in a test, a module-level import cannot.
    """
    return Settings()


#: Importable singleton, matching `from monoapi.core._settings import settings`
#: in the backend. Reading it at import time freezes the environment as it was
#: when the module first loaded, so anything that needs to react to a changed
#: environment — tests, above all — calls `get_settings()` instead.
settings: Settings = get_settings()
