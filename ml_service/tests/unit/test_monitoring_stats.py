"""Tests for the statistics behind the cohort comparison.

This is the part of the platform most able to produce a confident wrong answer.
A confidence interval that is subtly too narrow does not crash, does not fail a
schema check and does not look wrong on a dashboard — it just manufactures
significance. So the maths is tested directly, on data where the answer is known.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monetka.monitoring.performance import (
    LATENCY_BUDGET_MS,
    MAX_CLASS_CONCENTRATION,
    MIN_CONSULT_RATE,
    CohortEffect,
    Health,
    _required_sample_size,
    _welch_interval,
)

RNG = np.random.default_rng(20260305)


# ------------------------------------------------------- Welch intervals ---


def test_identical_samples_give_an_interval_containing_zero() -> None:
    sample = pd.Series(RNG.normal(size=500))
    diff, low, high = _welch_interval(sample, sample)
    assert diff == pytest.approx(0.0)
    assert low <= 0 <= high


def test_clearly_shifted_samples_exclude_zero() -> None:
    a = pd.Series(RNG.normal(loc=1.0, scale=1.0, size=500))
    b = pd.Series(RNG.normal(loc=0.0, scale=1.0, size=500))
    diff, low, _ = _welch_interval(a, b)
    assert diff > 0
    assert low > 0, "a one-sigma shift over 500 points should be unambiguous"


def test_interval_brackets_the_difference() -> None:
    a = pd.Series(RNG.normal(loc=0.3, size=400))
    b = pd.Series(RNG.normal(loc=0.0, size=400))
    diff, low, high = _welch_interval(a, b)
    assert low < diff < high


def test_interval_narrows_as_the_sample_grows() -> None:
    """More data must buy precision — otherwise the maths is wrong somewhere."""
    small_a = pd.Series(RNG.normal(loc=0.2, size=50))
    small_b = pd.Series(RNG.normal(size=50))
    large_a = pd.Series(RNG.normal(loc=0.2, size=5_000))
    large_b = pd.Series(RNG.normal(size=5_000))

    _, low_s, high_s = _welch_interval(small_a, small_b)
    _, low_l, high_l = _welch_interval(large_a, large_b)
    assert (high_l - low_l) < (high_s - low_s)


def test_unequal_variance_is_handled() -> None:
    """Welch, not Student: assuming equal variance here would be a free error."""
    a = pd.Series(RNG.normal(loc=0.0, scale=0.1, size=300))
    b = pd.Series(RNG.normal(loc=0.0, scale=3.0, size=300))
    diff, low, high = _welch_interval(a, b)
    assert np.isfinite(low) and np.isfinite(high)
    assert low <= diff <= high


def test_single_observation_returns_no_interval() -> None:
    diff, low, high = _welch_interval(pd.Series([1.0]), pd.Series([0.0]))
    assert diff == 1.0
    assert np.isnan(low) and np.isnan(high)


def test_zero_variance_collapses_the_interval() -> None:
    a = pd.Series([1.0] * 10)
    b = pd.Series([0.0] * 10)
    diff, low, high = _welch_interval(a, b)
    assert diff == low == high == 1.0


# ----------------------------------------------------------- sample size ---


def test_required_sample_size_falls_as_the_effect_grows() -> None:
    small_effect = _required_sample_size(0.01, pooled_sd=1.0)
    large_effect = _required_sample_size(0.5, pooled_sd=1.0)
    assert small_effect is not None and large_effect is not None
    assert large_effect < small_effect


def test_required_sample_size_matches_the_textbook_value() -> None:
    """One standard deviation apart needs ~16 per arm at 80% power."""
    assert _required_sample_size(1.0, pooled_sd=1.0) == 16


def test_required_sample_size_is_none_for_a_zero_effect() -> None:
    assert _required_sample_size(0.0, pooled_sd=1.0) is None


def test_required_sample_size_is_none_when_unmeasurable() -> None:
    assert _required_sample_size(1.0, pooled_sd=0.0) is None
    # An effect this tiny needs more profiles than the country has children.
    assert _required_sample_size(1e-9, pooled_sd=1.0) is None


# ---------------------------------------------------------------- verdict --


def _effect(
    diff: float, low: float, high: float, n: int = 400, required: int | None = None
) -> CohortEffect:
    return CohortEffect(
        metric="plan_adherence",
        model_profiles=n,
        rule_profiles=n,
        model_mean=0.8,
        rule_mean=0.8 - diff,
        difference=diff,
        ci_low=low,
        ci_high=high,
        pooled_sd=0.1,
        required_n_per_arm=required,
    )


def test_interval_spanning_zero_is_not_significant() -> None:
    assert not _effect(0.01, -0.02, 0.04).significant


def test_interval_above_zero_is_significant() -> None:
    effect = _effect(0.05, 0.01, 0.09)
    assert effect.significant
    assert effect.verdict == "model cohort better"


def test_interval_below_zero_reports_harm() -> None:
    effect = _effect(-0.05, -0.09, -0.01)
    assert effect.significant
    assert effect.verdict == "model cohort worse"


def test_underpowered_result_says_how_many_are_needed() -> None:
    """«No difference» and «not enough data» must not read the same.

    Teams routinely read the second as the first and ship on that basis.
    """
    effect = _effect(0.01, -0.02, 0.04, n=400, required=5_000)
    assert "underpowered" in effect.note
    assert "5,000" in effect.note


def test_well_powered_null_says_the_effect_is_zero() -> None:
    effect = _effect(0.001, -0.002, 0.004, n=10_000, required=500)
    assert "well powered" in effect.note


def test_significant_effect_says_so() -> None:
    assert _effect(0.05, 0.01, 0.09).note == "effect detected"


# ----------------------------------------------------------------- health --


def _health(**overrides) -> Health:
    base = {
        "hints_total": 1_000,
        "model_consults": 400,
        "consult_rate": 0.4,
        "avg_latency_ms": 18.0,
        "p95_latency_ms": 33.0,
        "slow_inferences": 0,
        "distinct_hints": 8,
        "top_class_share": 0.31,
        "predicted_distribution": {"planner": 120, "spender": 100, "saver": 90, "explorer": 90},
    }
    return Health(**{**base, **overrides})


def test_healthy_deployment_reports_no_problems() -> None:
    health = _health()
    assert health.healthy
    assert health.problems == []


def test_latency_over_budget_is_flagged() -> None:
    health = _health(p95_latency_ms=LATENCY_BUDGET_MS + 1)
    assert not health.healthy
    assert "budget" in health.problems[0]


def test_personalisation_effectively_off_is_flagged() -> None:
    health = _health(consult_rate=MIN_CONSULT_RATE / 2)
    assert not health.healthy
    assert "personalisation" in " ".join(health.problems)


def test_class_collapse_is_flagged() -> None:
    """The earliest visible sign of a broken feature pipeline."""
    health = _health(top_class_share=MAX_CLASS_CONCENTRATION + 0.05)
    assert not health.healthy
    assert "one class" in " ".join(health.problems)


def test_single_hint_collapse_is_flagged() -> None:
    health = _health(distinct_hints=1)
    assert not health.healthy
    assert "collapsed" in " ".join(health.problems)


def test_a_quiet_deployment_is_not_called_collapsed() -> None:
    """Few events is not the same as a broken advisor."""
    health = _health(distinct_hints=1, hints_total=10)
    assert "collapsed" not in " ".join(health.problems)


def test_missing_latency_does_not_crash_the_check() -> None:
    """No model consulted at all means no latency to judge."""
    health = _health(avg_latency_ms=None, p95_latency_ms=None, top_class_share=None)
    assert health.problems == []
