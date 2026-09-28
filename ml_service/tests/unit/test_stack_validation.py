"""Tests for the static stack validator.

Half of these deliberately break the compose file and require the validator to
notice. A checker that cannot fail proves nothing, and this one is the only
thing standing between the repository and a `docker compose up` that dies on a
machine where nobody can debug it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from monetka.common.config import REPO_ROOT
from monetka.infra.stack import validate_dockerfile, validate_stack

DOCKER_DIR = REPO_ROOT / "infra" / "docker"


# ----------------------------------------------------- the real stack ------


def test_the_shipped_stack_validates() -> None:
    report = validate_stack()
    assert report.passed, "\n".join(f"{f.check}: {f.detail}" for f in report.errors)


def test_every_dockerfile_validates() -> None:
    dockerfiles = sorted(DOCKER_DIR.glob("Dockerfile*"))
    assert dockerfiles, "no Dockerfiles found"
    for path in dockerfiles:
        findings = validate_dockerfile(path)
        assert not findings, "\n".join(f"{f.check}: {f.detail}" for f in findings)


def test_memory_budget_is_reported_per_profile() -> None:
    report = validate_stack()
    assert "default" in report.memory_estimate_mb
    assert "full" in report.memory_estimate_mb
    # `full` is a superset of `default`, so it cannot need less.
    assert report.memory_estimate_mb["full"] > report.memory_estimate_mb["default"]
    assert report.long_running_counts["full"] > report.long_running_counts["default"]


def test_oneshot_containers_are_excluded_from_the_budget() -> None:
    """Init containers exit before the stack serves; counting them overstates peak."""
    report = validate_stack()
    assert report.long_running_counts["default"] < len(report.services)


# -------------------------------------------- the validator can fail -------


def _write(tmp_path: Path, compose: dict) -> Path:
    path = tmp_path / "docker-compose.yml"
    path.write_text(yaml.safe_dump(compose), encoding="utf-8")
    return path


def _env(tmp_path: Path, names: str = "") -> Path:
    path = tmp_path / ".env.template"
    path.write_text(names, encoding="utf-8")
    return path


def _checks(report) -> set[str]:
    return {f.check for f in report.errors}


def test_floating_tag_is_rejected(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres"}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "pinned_images" in _checks(report)


def test_latest_tag_is_rejected(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres:latest"}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "pinned_images" in _checks(report)


def test_port_collision_is_detected(tmp_path: Path) -> None:
    compose = {
        "services": {
            "a": {"image": "postgres:16", "ports": ["8080:8080"]},
            "b": {"image": "redis:7.2", "ports": ["8080:9000"]},
        }
    }
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "port_collision" in _checks(report)


def test_missing_bind_mount_is_detected(tmp_path: Path) -> None:
    """Docker silently creates an empty directory — the service then misbehaves."""
    compose = {"services": {"a": {"image": "postgres:16", "volumes": ["./nope:/etc/x:ro"]}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "bind_mount_exists" in _checks(report)


def test_existing_bind_mount_passes(tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    compose = {"services": {"a": {"image": "postgres:16", "volumes": ["./conf:/etc/x:ro"]}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "bind_mount_exists" not in _checks(report)


def test_dangling_depends_on_is_detected(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres:16", "depends_on": ["ghost"]}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "depends_on_exists" in _checks(report)


def test_self_dependency_is_detected(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres:16", "depends_on": ["a"]}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "depends_on_cycle" in _checks(report)


def test_default_service_depending_on_a_profiled_one_is_detected(tmp_path: Path) -> None:
    """`docker compose up` cannot resolve it, and the message is unhelpful."""
    compose = {
        "services": {
            "a": {"image": "postgres:16", "depends_on": ["b"]},
            "b": {"image": "redis:7.2", "profiles": ["full"]},
        }
    }
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "profile_dependency" in _checks(report)


def test_undocumented_env_var_is_detected(tmp_path: Path) -> None:
    """A variable with no default and no .env entry breaks a fresh clone."""
    compose = {"services": {"a": {"image": "postgres:16", "environment": {"X": "${SECRET_TOKEN}"}}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "env_documented" in _checks(report)


def test_env_var_with_a_default_is_fine(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres:16", "environment": {"X": "${THING:-ok}"}}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "env_documented" not in _checks(report)


def test_env_var_declared_in_example_is_fine(tmp_path: Path) -> None:
    compose = {"services": {"a": {"image": "postgres:16", "environment": {"X": "${DB_USER}"}}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path, "DB_USER=monetka\n"))
    assert "env_documented" not in _checks(report)


def test_service_healthy_without_a_healthcheck_is_detected(tmp_path: Path) -> None:
    """The dependant hangs until timeout instead of failing fast."""
    compose = {
        "services": {
            "a": {"image": "postgres:16", "depends_on": {"b": {"condition": "service_healthy"}}},
            "b": {"image": "redis:7.2"},
        }
    }
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "healthcheck_present" in _checks(report)


def test_service_without_image_or_build_is_detected(tmp_path: Path) -> None:
    compose = {"services": {"a": {"ports": ["1:1"]}}}
    report = validate_stack(_write(tmp_path, compose), _env(tmp_path))
    assert "image_or_build" in _checks(report)


def test_missing_compose_file_is_reported(tmp_path: Path) -> None:
    report = validate_stack(tmp_path / "absent.yml", _env(tmp_path))
    assert "compose_present" in _checks(report)


# ------------------------------------------------- dockerfile checks -------


def test_missing_copy_source_is_detected(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        textwrap.dedent(
            """
            FROM python:3.12-slim
            COPY definitely_not_a_real_path ./
            USER nobody
            """
        ),
        encoding="utf-8",
    )
    findings = validate_dockerfile(dockerfile)
    assert any(f.check == "copy_source_exists" for f in findings)


def test_root_container_is_detected(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text('FROM python:3.12-slim\nCMD ["true"]\n', encoding="utf-8")
    findings = validate_dockerfile(dockerfile)
    assert any(f.check == "non_root_user" for f in findings)


def test_absent_dockerfile_is_reported(tmp_path: Path) -> None:
    findings = validate_dockerfile(tmp_path / "nope")
    assert findings and findings[0].check == "dockerfile_exists"


@pytest.mark.parametrize("severity", ["error", "warning"])
def test_finding_severity_round_trips(severity: str) -> None:
    from monetka.infra.stack import Finding

    finding = Finding(severity, "x", "y")
    assert finding.is_error == (severity == "error")


class TestEnvTemplateCoversSettings:
    """`.env.template` is the only place a reviewer learns what can be set.

    A field added to `Settings` without a line here is invisible: it works on
    the machine of whoever added it and is undiscoverable to everyone else.
    """

    #: Paths default to directories inside `ml_service/`. Writing an absolute
    #: path into a template that gets copied verbatim is worse than omitting it:
    #: it would point at the author's machine.
    OMITTED_ON_PURPOSE: ClassVar[set[str]] = {
        "data_dir",
        "warehouse_path",
        "artifacts_dir",
        "api_model_dir",
    }

    def test_every_setting_is_documented(self) -> None:
        from monetka.common.config import REPO_ROOT, Settings

        template = (REPO_ROOT / ".env.template").read_text(encoding="utf-8")
        documented = {
            line.split("=", 1)[0].strip()
            for line in template.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }

        missing = sorted(
            f"MONETKA_{name.upper()}"
            for name in Settings.model_fields
            if name not in self.OMITTED_ON_PURPOSE and f"MONETKA_{name.upper()}" not in documented
        )
        assert not missing, f"settings absent from .env.template: {missing}"

    def test_the_template_names_no_unknown_settings(self) -> None:
        """A `MONETKA_*` line that matches no field is a typo or a leftover."""
        from monetka.common.config import REPO_ROOT, Settings

        template = (REPO_ROOT / ".env.template").read_text(encoding="utf-8")
        known = {f"MONETKA_{name.upper()}" for name in Settings.model_fields}
        unknown = sorted(
            key
            for line in template.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
            for key in [line.split("=", 1)[0].strip()]
            if key.startswith("MONETKA_") and key not in known
        )
        assert not unknown, f".env.template sets settings that do not exist: {unknown}"


class TestDockerfileExtras:
    """An extra that pyproject does not declare must fail the check, not the build.

    pip treats an unknown extra as a warning buried in hundreds of lines of
    download output, installs everything else and exits 0. The Dockerfile asked
    for a `quality` extra that never existed, and the image built cleanly for as
    long as it was there.
    """

    def test_the_shipped_dockerfiles_name_only_real_extras(self) -> None:
        from monetka.common.config import REPO_ROOT
        from monetka.infra.stack import validate_dockerfile

        dockerfiles = sorted((REPO_ROOT / "infra" / "docker").glob("Dockerfile*"))
        assert dockerfiles, "no Dockerfiles found — the glob or the layout changed"
        for path in dockerfiles:
            bad = [f for f in validate_dockerfile(path) if f.check == "extra_declared"]
            assert not bad, [f.detail for f in bad]

    def test_an_undeclared_extra_is_reported(self, tmp_path) -> None:
        from monetka.infra.stack import validate_dockerfile

        probe = tmp_path / "Dockerfile"
        probe.write_text(
            'FROM python:3.12-slim\nRUN pip install ".[stream,not-a-real-extra]"\nUSER nobody\n',
            encoding="utf-8",
        )
        reported = [f for f in validate_dockerfile(probe) if f.check == "extra_declared"]
        assert len(reported) == 1
        assert "not-a-real-extra" in reported[0].detail

    def test_a_declared_extra_is_accepted(self, tmp_path) -> None:
        from monetka.infra.stack import validate_dockerfile

        probe = tmp_path / "Dockerfile"
        probe.write_text(
            'FROM python:3.12-slim\nRUN pip install ".[stream,lake]"\nUSER nobody\n',
            encoding="utf-8",
        )
        assert not [f for f in validate_dockerfile(probe) if f.check == "extra_declared"]
