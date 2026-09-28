"""Tests for the pieces that usually go unverified until they fail in production.

Dashboards, alert rules, compose files and CLI wiring are all code that nobody
runs locally. A malformed dashboard is discovered when someone opens Grafana
during an incident; a broken CLI command when a reviewer follows the README.
These are cheap tests for exactly those cases.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from unittest import mock

import pytest
import yaml
from typer.testing import CliRunner

from monetka import cli as cli_module
from monetka.cli import app
from monetka.common.config import REPO_ROOT

INFRA = REPO_ROOT / "infra"
runner = CliRunner()


# ------------------------------------------------------------- dashboards --


def test_every_dashboard_is_valid_json_with_panels() -> None:
    dashboards = list((INFRA / "grafana" / "dashboards").glob("*.json"))
    assert dashboards, "grafana provisioning mounts a directory with no dashboards in it"
    for path in dashboards:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        assert dashboard.get("uid"), f"{path.name}: no uid — provisioning needs one"
        assert dashboard.get("title"), f"{path.name}: no title"
        assert dashboard.get("panels"), f"{path.name}: no panels"


def test_dashboard_panels_are_documented() -> None:
    """A panel without a description is a number nobody can act on."""
    for path in (INFRA / "grafana" / "dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        undocumented = [
            panel.get("title", "<untitled>")
            for panel in dashboard["panels"]
            if panel.get("type") != "text" and not panel.get("description")
        ]
        assert not undocumented, f"{path.name}: undocumented panels {undocumented}"


def test_dashboard_panel_ids_are_unique() -> None:
    for path in (INFRA / "grafana" / "dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        ids = [panel["id"] for panel in dashboard["panels"]]
        assert len(ids) == len(set(ids)), f"{path.name}: duplicate panel ids"


# ------------------------------------------------------------ alert rules --


def _alert_rules() -> list[dict]:
    rules: list[dict] = []
    for path in (INFRA / "prometheus" / "rules").glob("*.yml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in document["groups"]:
            rules.extend(rule for rule in group["rules"] if "alert" in rule)
    return rules


def test_alert_rules_parse() -> None:
    assert _alert_rules(), "prometheus is configured to load rules but none exist"


def test_every_alert_names_an_action() -> None:
    """An alert without an action is a dashboard panel that wakes someone up.

    Alerts nobody can act on are how teams learn to ignore the ones that matter.
    """
    for rule in _alert_rules():
        annotations = rule.get("annotations", {})
        assert annotations.get("summary"), f"{rule['alert']}: no summary"
        assert annotations.get("action"), f"{rule['alert']}: no action to take"


def test_every_alert_has_severity_and_duration() -> None:
    for rule in _alert_rules():
        assert rule.get("labels", {}).get("severity"), f"{rule['alert']}: no severity"
        assert rule.get("for"), f"{rule['alert']}: fires instantly, will flap"


def test_compose_file_is_valid_and_pins_images() -> None:
    """A floating tag makes the stack unreproducible between two `make up` runs."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services, "no services defined"

    floating = [
        name
        for name, spec in services.items()
        if "image" in spec and (":" not in spec["image"] or spec["image"].endswith(":latest"))
    ]
    assert not floating, f"services on a floating tag: {floating}"


def test_compose_mounts_the_rules_directory() -> None:
    """Prometheus is told to read rules; the directory has to reach the container."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    mounts = compose["services"]["prometheus"]["volumes"]
    assert any("prometheus/rules" in mount for mount in mounts)


# -------------------------------------------------------------------- CLI --


def test_help_lists_the_pipeline_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "generate",
        "bronze",
        "silver",
        "gold",
        "quality",
        "train",
        "export",
        "monitor",
        "contracts",
    ):
        assert command in result.stdout, f"`{command}` missing from --help"


@pytest.mark.parametrize(
    "command",
    [
        "generate",
        "bronze",
        "silver",
        "gold",
        "quality",
        "train",
        "export",
        "drift",
        "monitor",
        "contracts",
        "demo",
        "serve",
    ],
)
def test_every_command_has_help(command: str) -> None:
    """A command whose --help fails is a command that fails at import time."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, f"`{command} --help` failed:\n{result.output}"


def test_contracts_check_passes() -> None:
    result = runner.invoke(app, ["contracts", "--check"])
    assert result.exit_code == 0, result.output


# -------------------------------------------------------- stream consumer --


def _event_json(**overrides) -> str:
    payload = {"cold_start": True, "startup_latency_ms": 900}
    record = {
        "event_id": str(uuid.uuid4()),
        "event_name": "app_opened",
        "schema_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "profile_pseudo_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "period_no": 1,
        "app_version": "1.0.0",
        "android_api_level": 33,
        "demo_mode": False,
        "payload": json.dumps(payload),
    }
    record.update(overrides)
    return json.dumps(record)


def test_stream_parse_accepts_a_valid_message() -> None:
    from monetka.ingestion.stream_consumer import _parse

    row = _parse(_event_json(), datetime.now(UTC))
    assert isinstance(row, tuple)
    assert row[1] == "app_opened"


def test_stream_parse_rejects_malformed_json() -> None:
    """A poison message must be described, not crash the consumer."""
    from monetka.ingestion.stream_consumer import _parse

    reason = _parse("{not json", datetime.now(UTC))
    assert isinstance(reason, str)
    assert "JSONDecodeError" in reason or "Expecting" in reason


def test_stream_parse_rejects_contract_violation() -> None:
    from monetka.ingestion.stream_consumer import _parse

    reason = _parse(_event_json(android_api_level=10), datetime.now(UTC))
    assert isinstance(reason, str)
    assert "ValidationError" in reason


def test_stream_parse_rejects_personal_data() -> None:
    """The privacy guard applies on the streaming path too, not just in batch."""
    from monetka.ingestion.stream_consumer import _parse

    reason = _parse(
        _event_json(
            payload=json.dumps({"cold_start": True, "startup_latency_ms": 5, "child_name": "Вася"})
        ),
        datetime.now(UTC),
    )
    assert isinstance(reason, str)
    assert "ValidationError" in reason


def test_stream_parse_preserves_supplied_ingested_at() -> None:
    from monetka.ingestion.stream_consumer import _parse

    delivered = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
    row = _parse(_event_json(ingested_at=delivered.isoformat()), datetime.now(UTC))
    assert isinstance(row, tuple)
    assert row[4] == delivered


class TestConsoleEncoding:
    """`monetka` must survive a non-UTF-8 console.

    A Russian Windows install gives stdout cp1251, and the CLI's `✓`, `≈` and
    box-drawing characters are not in it. Before `_force_utf8_output`, a
    reviewer running `monetka stack-check` on such a machine got a traceback
    instead of the report — after the checks had already passed.
    """

    def test_reconfigures_a_cp1251_stream(self) -> None:
        from monetka.cli import _force_utf8_output

        calls: list[dict[str, object]] = []

        class FakeStream:
            encoding = "cp1251"

            def reconfigure(self, **kwargs: object) -> None:
                calls.append(kwargs)
                self.encoding = str(kwargs["encoding"])

        stream = FakeStream()
        with (
            mock.patch.object(cli_module.sys, "stdout", stream),
            mock.patch.object(cli_module.sys, "stderr", stream),
        ):
            _force_utf8_output()

        assert calls, "a cp1251 stream must be reconfigured"
        assert calls[0]["encoding"] == "utf-8"
        # `replace` rather than `strict`: a stream that still cannot encode some
        # character should print a placeholder, never abort a finished command.
        assert calls[0]["errors"] == "replace"

    def test_leaves_a_utf8_stream_alone(self) -> None:
        from monetka.cli import _force_utf8_output

        calls: list[dict[str, object]] = []

        class FakeStream:
            encoding = "UTF-8"

            def reconfigure(self, **kwargs: object) -> None:
                calls.append(kwargs)

        stream = FakeStream()
        with (
            mock.patch.object(cli_module.sys, "stdout", stream),
            mock.patch.object(cli_module.sys, "stderr", stream),
        ):
            _force_utf8_output()

        assert not calls, "reconfiguring an already-UTF-8 stream can only lose state"

    def test_survives_a_stream_that_refuses(self) -> None:
        """Pytest's captured stdout raises on reconfigure; that must not be fatal."""
        from monetka.cli import _force_utf8_output

        class StubbornStream:
            encoding = "cp1251"

            def reconfigure(self, **kwargs: object) -> None:
                raise ValueError("underlying stream is detached")

        stream = StubbornStream()
        with (
            mock.patch.object(cli_module.sys, "stdout", stream),
            mock.patch.object(cli_module.sys, "stderr", stream),
        ):
            _force_utf8_output()  # must not raise


class TestRepoRootDetection:
    """`REPO_ROOT` decides where every default path lives.

    It used to be `parents[3]` with no check. That is correct in a checkout and
    wrong in the Docker image, where the package is installed into
    site-packages: the API crashed on startup trying to create
    `/opt/venv/lib/python3.12/artifacts` as uid 999. The test suite could not
    see it, because tests only ever run from a checkout.
    """

    def test_uses_the_checkout_when_the_marker_is_there(self, tmp_path) -> None:
        import monetka.common.config as config_module
        from monetka.common.config import _detect_repo_root

        root = tmp_path / "checkout"
        (root / "src" / "monetka" / "common").mkdir(parents=True)
        (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        fake_file = root / "src" / "monetka" / "common" / "config.py"
        fake_file.write_text("", encoding="utf-8")

        with mock.patch.object(config_module, "__file__", str(fake_file)):
            assert _detect_repo_root() == root

    def test_falls_back_to_cwd_when_installed(self, tmp_path, monkeypatch) -> None:
        import monetka.common.config as config_module
        from monetka.common.config import _detect_repo_root

        # Mimic site-packages: no pyproject.toml three levels up.
        installed = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
        pkg = installed / "monetka" / "common"
        pkg.mkdir(parents=True)
        fake_file = pkg / "config.py"
        fake_file.write_text("", encoding="utf-8")

        workdir = tmp_path / "app"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        with mock.patch.object(config_module, "__file__", str(fake_file)):
            assert _detect_repo_root() == workdir

    def test_the_real_root_is_writable(self) -> None:
        """Whatever was detected here must be somewhere we can actually write."""
        from monetka.common.config import REPO_ROOT

        assert os.access(REPO_ROOT, os.W_OK), (
            f"{REPO_ROOT} is not writable — every default path derives from it"
        )


class TestDbtPackagesPrecondition:
    """`dbt_packages/` must exist before dbt is asked to compile anything.

    dbt stops with «expects 1 package(s) ... found only 0» and exit code 2,
    which names packages rather than the pipeline stage that failed. In a
    checkout the directory is usually there from an earlier `dbt deps`; in a
    fresh container it is not, and the gold stage died on a clean machine.
    """

    def test_installs_when_the_directory_is_empty(self, tmp_path) -> None:
        from monetka.ingestion import gold as gold_module

        empty = tmp_path / "dbt_packages"
        empty.mkdir()
        calls: list[tuple[str, ...]] = []

        with (
            mock.patch.object(gold_module, "DBT_PACKAGES_DIR", empty),
            mock.patch.object(gold_module, "run_dbt", lambda *args: calls.append(args)),
        ):
            gold_module.ensure_dbt_packages()

        assert calls == [("deps",)]

    def test_skips_when_packages_are_present(self, tmp_path) -> None:
        from monetka.ingestion import gold as gold_module

        installed = tmp_path / "dbt_packages"
        (installed / "dbt_utils").mkdir(parents=True)
        calls: list[tuple[str, ...]] = []

        with (
            mock.patch.object(gold_module, "DBT_PACKAGES_DIR", installed),
            mock.patch.object(gold_module, "run_dbt", lambda *args: calls.append(args)),
        ):
            gold_module.ensure_dbt_packages()

        assert calls == [], "re-running `dbt deps` on every build wastes a network round trip"

    def test_missing_directory_is_not_an_error(self, tmp_path) -> None:
        """A container that never ran dbt has no directory at all, not an empty one."""
        from monetka.ingestion import gold as gold_module

        calls: list[tuple[str, ...]] = []
        with (
            mock.patch.object(gold_module, "DBT_PACKAGES_DIR", tmp_path / "never-created"),
            mock.patch.object(gold_module, "run_dbt", lambda *args: calls.append(args)),
        ):
            gold_module.ensure_dbt_packages()

        assert calls == [("deps",)]
