"""Tests for drift measurement and the on-device export path."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from monetka.common.config import REPO_ROOT
from monetka.monitoring.drift import (
    PSI_MATERIAL,
    PSI_STABLE,
    FeatureDrift,
    population_stability_index,
)

RNG = np.random.default_rng(20260305)


# --------------------------------------------------------------- PSI --------


def test_identical_distributions_have_near_zero_psi() -> None:
    sample = RNG.normal(size=5_000)
    assert population_stability_index(sample, sample) < 0.01


def test_shifted_distribution_is_detected() -> None:
    reference = RNG.normal(loc=0.0, size=5_000)
    shifted = RNG.normal(loc=1.5, size=5_000)
    assert population_stability_index(reference, shifted) > PSI_MATERIAL


def test_psi_grows_with_the_size_of_the_shift() -> None:
    reference = RNG.normal(size=5_000)
    small = population_stability_index(reference, RNG.normal(loc=0.2, size=5_000))
    large = population_stability_index(reference, RNG.normal(loc=2.0, size=5_000))
    assert large > small


def test_psi_is_finite_when_a_bin_is_empty() -> None:
    """Smoothing must keep PSI finite; an infinite score is unreportable."""
    reference = RNG.normal(size=1_000)
    disjoint = RNG.normal(loc=50.0, size=1_000)
    psi = population_stability_index(reference, disjoint)
    assert np.isfinite(psi)
    assert psi > PSI_MATERIAL


def test_constant_feature_reports_no_drift() -> None:
    constant = np.ones(1_000)
    assert population_stability_index(constant, constant) == 0.0


def test_empty_sample_is_handled() -> None:
    assert population_stability_index(np.array([]), RNG.normal(size=10)) == 0.0


def test_nan_values_are_ignored() -> None:
    reference = np.concatenate([RNG.normal(size=1_000), np.full(50, np.nan)])
    current = RNG.normal(size=1_000)
    assert np.isfinite(population_stability_index(reference, current))


@pytest.mark.parametrize(
    ("psi", "expected"),
    [(0.05, "stable"), (0.15, "moderate"), (0.5, "material")],
)
def test_psi_bands(psi: float, expected: str) -> None:
    drift = FeatureDrift("f", psi, psi > PSI_MATERIAL, 0.0, 0.0)
    assert drift.band == expected


def test_band_thresholds_are_ordered() -> None:
    assert PSI_STABLE < PSI_MATERIAL


# ------------------------------------------------------- export safety ------


EXPORT_MODULE = REPO_ROOT / "src" / "monetka" / "ml" / "export" / "onnx_export.py"


def _module_level_import_order(path: Path) -> list[str]:
    """Names of top-level imports, in source order."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_import_order_is_safe() -> None:
    """`skl2onnx` must be imported before `onnxruntime`.

    With onnx 1.23 / onnxruntime 1.30 / skl2onnx 1.20 on Windows, the reverse
    order makes the converter terminate the interpreter with an access
    violation — no exception, no traceback. A "tidy the imports" commit that
    reorders these would break the export silently, so the order is asserted
    here rather than left to a comment.
    """
    order = _module_level_import_order(EXPORT_MODULE)
    skl = next((i for i, name in enumerate(order) if name.startswith("skl2onnx")), None)
    ort = next((i for i, name in enumerate(order) if name.startswith("onnxruntime")), None)

    assert skl is not None, "skl2onnx must be imported at module level"
    assert ort is not None, "onnxruntime must be imported at module level"
    assert skl < ort, (
        "skl2onnx must be imported BEFORE onnxruntime — the reverse order "
        "crashes the interpreter during conversion (see the module docstring)"
    )


def test_export_module_has_no_function_level_onnx_imports() -> None:
    """Re-importing inside a function would reintroduce the ordering hazard."""
    tree = ast.parse(EXPORT_MODULE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                offenders.extend(
                    f"{node.name}: {a.name}"
                    for a in child.names
                    if a.name.startswith(("onnx", "skl2onnx"))
                )
            elif isinstance(child, ast.ImportFrom) and (child.module or "").startswith(
                ("onnx", "skl2onnx")
            ):
                offenders.append(f"{node.name}: {child.module}")
    assert not offenders, f"onnx imports inside functions: {offenders}"
