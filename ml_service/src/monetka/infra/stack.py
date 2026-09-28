"""Static validation of the container stack.

`docker compose up` fails for a small set of boring reasons, and almost all of
them are visible in the files before anything is started: a host port claimed
twice, a bind mount whose source does not exist, an environment variable with no
default and no entry in `.env.template`, a `depends_on` pointing at a service
that was renamed.

Every one of those costs a build-and-wait cycle to discover, and on a machine
without a Docker daemon they cannot be discovered at all. So they are checked
here instead, and wired into CI.

What this **cannot** check is equally worth stating: whether the images pull,
whether the services actually become healthy, and whether they interoperate.
Those need a daemon. `monetka stack-check` says so in its output rather than
letting a green result be read as "the stack works".
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from monetka.common.config import REPO_ROOT
from monetka.common.logging import get_logger

log = get_logger("infra.stack")

COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_TEMPLATE = REPO_ROOT / ".env.template"

#: `${VAR}` or `${VAR:-default}`.
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?-[^}]*)?\}")

#: Rough working-set of each image, in MB. Used only to warn that a profile will
#: not fit — a stack that swaps is indistinguishable from a stack that hangs,
#: and the difference costs an hour to work out.
_MEMORY_HINT_MB: dict[str, int] = {
    "redpanda": 1200,
    "seaweedfs": 300,
    "iceberg-rest": 450,
    # Capped to 1 GB heap by infra/trino/jvm.config; stock Trino would take ~2 GB.
    "trino": 1200,
    "postgres": 250,
    "api": 400,
    "ingestor": 300,
    "mlflow": 500,
    "airflow": 1600,
    "prometheus": 300,
    "grafana": 300,
}


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str  # "error" | "warning"
    check: str
    detail: str

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(slots=True)
class StackReport:
    findings: list[Finding] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    profiles: dict[str, list[str]] = field(default_factory=dict)
    memory_estimate_mb: dict[str, int] = field(default_factory=dict)
    #: Services that stay up, per profile. One-shot init containers are excluded
    #: because they exit before the rest of the stack is serving.
    long_running_counts: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.is_error]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if not f.is_error]

    @property
    def passed(self) -> bool:
        return not self.errors


def _load_compose(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _declared_env_defaults(path: Path) -> set[str]:
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.add(line.split("=", 1)[0].strip())
    return names


def _walk_strings(node: Any) -> Iterator[str]:
    """Yield every string anywhere in the compose document."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)


def validate_stack(
    compose_file: Path | None = None, env_template: Path | None = None
) -> StackReport:
    """Check everything about the stack that can be checked without a daemon."""
    compose_path = compose_file or COMPOSE_FILE
    env_path = env_template or ENV_TEMPLATE
    report = StackReport()

    if not compose_path.exists():
        report.findings.append(Finding("error", "compose_present", f"{compose_path} not found"))
        return report

    compose = _load_compose(compose_path)
    services: dict[str, Any] = compose.get("services") or {}
    report.services = sorted(services)
    root = compose_path.parent

    if not services:
        report.findings.append(Finding("error", "services_defined", "no services in the file"))
        return report

    # ------------------------------------------------ image or build ------
    for name, spec in services.items():
        if "image" not in spec and "build" not in spec:
            report.findings.append(
                Finding("error", "image_or_build", f"{name}: neither `image` nor `build`")
            )

    # ------------------------------------------------- pinned versions ----
    for name, spec in services.items():
        image = spec.get("image")
        if image and (":" not in image or image.endswith(":latest")):
            report.findings.append(
                Finding(
                    "error",
                    "pinned_images",
                    f"{name}: `{image}` is a floating tag — two `make up` runs "
                    "would not give the same stack",
                )
            )

    # --------------------------------------------------- host ports -------
    claimed: dict[str, str] = {}
    for name, spec in services.items():
        for mapping in spec.get("ports", []) or []:
            text = str(mapping)
            host_port = text.split(":")[0].strip('"')
            if not host_port.isdigit():
                continue
            if host_port in claimed:
                report.findings.append(
                    Finding(
                        "error",
                        "port_collision",
                        f"host port {host_port} claimed by both "
                        f"`{claimed[host_port]}` and `{name}`",
                    )
                )
            else:
                claimed[host_port] = name

    # ------------------------------------------------- depends_on ---------
    for name, spec in services.items():
        depends = spec.get("depends_on") or {}
        targets = depends if isinstance(depends, list) else list(depends)
        for target in targets:
            if target not in services:
                report.findings.append(
                    Finding(
                        "error",
                        "depends_on_exists",
                        f"{name}: depends_on `{target}`, which is not a service",
                    )
                )
            elif target == name:
                report.findings.append(
                    Finding("error", "depends_on_cycle", f"{name}: depends on itself")
                )

    # A service in the default profile must not depend on one that only exists
    # under a profile — `docker compose up` would fail to resolve it.
    for name, spec in services.items():
        if spec.get("profiles"):
            continue
        depends = spec.get("depends_on") or {}
        for target in depends if isinstance(depends, list) else list(depends):
            target_profiles = services.get(target, {}).get("profiles")
            if target_profiles:
                report.findings.append(
                    Finding(
                        "error",
                        "profile_dependency",
                        f"{name} (default profile) depends on `{target}`, which is "
                        f"only started under profile {target_profiles}",
                    )
                )

    # ------------------------------------------------ bind mounts ---------
    for name, spec in services.items():
        for volume in spec.get("volumes", []) or []:
            text = str(volume)
            if not text.startswith("./") and not text.startswith("../"):
                continue  # named volume, not a bind mount
            source = text.split(":")[0]
            if not (root / source).exists():
                report.findings.append(
                    Finding(
                        "error",
                        "bind_mount_exists",
                        f"{name}: mounts `{source}`, which does not exist — "
                        "Docker would silently create an empty directory",
                    )
                )

    # ------------------------------------------------ build context -------
    for name, spec in services.items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        context = root / build.get("context", ".")
        if not context.exists():
            report.findings.append(
                Finding("error", "build_context", f"{name}: build context `{context}` missing")
            )
        dockerfile = build.get("dockerfile")
        if dockerfile and not (root / dockerfile).exists():
            report.findings.append(
                Finding("error", "dockerfile_exists", f"{name}: `{dockerfile}` missing")
            )

    # ------------------------------------------- environment variables ----
    declared = _declared_env_defaults(env_path)
    missing: set[str] = set()
    for text in _walk_strings(compose):
        for match in _VAR_PATTERN.finditer(text):
            name, default = match.group(1), match.group(2)
            if default:  # `${VAR:-fallback}` — safe without .env
                continue
            if name not in declared:
                missing.add(name)
    for name in sorted(missing):
        report.findings.append(
            Finding(
                "error",
                "env_documented",
                f"`${{{name}}}` has no default and is not in .env.template — "
                "the stack fails on a fresh clone",
            )
        )

    # ------------------------------------------------------ profiles ------
    for name, spec in services.items():
        for profile in spec.get("profiles", []) or []:
            report.profiles.setdefault(profile, []).append(name)

    # ------------------------------------------------ memory budget -------
    # One-shot init containers (`restart: "no"`) create topics or buckets and
    # exit, so they never hold memory at the same time as the long-running
    # services. Counting them would overstate the peak.
    def _is_oneshot(spec: dict[str, Any]) -> bool:
        return str(spec.get("restart", "")).strip('"') == "no"

    default_profile = [
        n for n, s in services.items() if not s.get("profiles") and not _is_oneshot(s)
    ]
    report.memory_estimate_mb["default"] = sum(_MEMORY_HINT_MB.get(n, 200) for n in default_profile)
    report.long_running_counts["default"] = len(default_profile)

    for profile, names in report.profiles.items():
        extra = [n for n in names if not _is_oneshot(services[n])]
        report.memory_estimate_mb[profile] = report.memory_estimate_mb["default"] + sum(
            _MEMORY_HINT_MB.get(n, 200) for n in extra
        )
        report.long_running_counts[profile] = len(default_profile) + len(extra)

    # -------------------------------------------------- healthchecks ------
    # Anything another service waits on must be able to report readiness, or the
    # dependant hangs until the timeout rather than failing quickly.
    waited_on: set[str] = set()
    for spec in services.values():
        depends = spec.get("depends_on") or {}
        if isinstance(depends, dict):
            waited_on.update(
                target
                for target, rule in depends.items()
                if isinstance(rule, dict) and rule.get("condition") == "service_healthy"
            )
    for name in sorted(waited_on):
        if name in services and "healthcheck" not in services[name]:
            report.findings.append(
                Finding(
                    "error",
                    "healthcheck_present",
                    f"{name}: another service waits for `service_healthy`, but it "
                    "declares no healthcheck",
                )
            )

    log.info(
        "stack_validated",
        services=len(services),
        errors=len(report.errors),
        warnings=len(report.warnings),
    )
    return report


def validate_dockerfile(path: Path) -> list[Finding]:
    """Check a Dockerfile's COPY sources exist and that it does not run as root."""
    findings: list[Finding] = []
    if not path.exists():
        return [Finding("error", "dockerfile_exists", f"{path} not found")]

    root = REPO_ROOT
    lines = path.read_text(encoding="utf-8").splitlines()
    saw_user = False

    for raw in lines:
        line = raw.strip()
        if line.upper().startswith("USER ") and "root" not in line.lower():
            saw_user = True
        if not line.upper().startswith("COPY "):
            continue
        parts = [p for p in line.split() if not p.startswith("--")][1:]
        if len(parts) < 2:
            continue
        for source in parts[:-1]:
            if source.startswith(("/", "$")) or "*" in source:
                continue
            if not (root / source).exists():
                findings.append(
                    Finding(
                        "error",
                        "copy_source_exists",
                        f"{path.name}: COPY source `{source}` does not exist",
                    )
                )

    if not saw_user:
        findings.append(
            Finding(
                "error",
                "non_root_user",
                f"{path.name}: never switches off root — a container that can "
                "write its own source tree is an avoidable risk",
            )
        )

    findings.extend(_check_declared_extras(path, lines))
    return findings


#: `pip install ".[stream,lake]"` — the bracketed group in a Dockerfile.
_EXTRAS_PATTERN = re.compile(r'pip\s+install\s+"\.\[([^\]]+)\]"')


def _check_declared_extras(path: Path, lines: list[str]) -> list[Finding]:
    """Every extra the Dockerfile installs must exist in `pyproject.toml`.

    pip does not fail on an unknown extra. It prints
    `WARNING: ... does not provide the extra 'quality'` in the middle of several
    hundred lines of download progress and installs everything else, so the
    image builds, the tests pass, and nobody finds out until the day the extra
    was supposed to bring something in.

    That is exactly what happened: the Dockerfile asked for a `quality` extra
    that was never declared. Nothing was missing — the data-quality checks have
    no third-party dependencies — but the build file claimed something untrue
    about itself for as long as it existed.
    """
    import tomllib

    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return []

    declared = set(
        tomllib.loads(pyproject.read_text(encoding="utf-8"))
        .get("project", {})
        .get("optional-dependencies", {})
    )

    findings: list[Finding] = []
    for raw in lines:
        match = _EXTRAS_PATTERN.search(raw)
        if not match:
            continue
        for extra in (part.strip() for part in match.group(1).split(",")):
            if extra and extra not in declared:
                findings.append(
                    Finding(
                        "error",
                        "extra_declared",
                        f"{path.name}: installs `.[{extra}]`, which pyproject.toml "
                        f"does not declare — pip only warns and moves on. "
                        f"Known extras: {', '.join(sorted(declared))}",
                    )
                )
    return findings
