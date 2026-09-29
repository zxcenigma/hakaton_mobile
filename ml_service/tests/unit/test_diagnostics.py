"""Tests for the evidence behind the modelling decisions.

`ml/diagnostics.py` is what regenerates the numbers the documentation relies on
— above all the horizon that `behaviour_segment` is scoped to. It had no tests
and no CLI entry point, so nothing ever ran it: a defence nobody can reach
defends nothing, and the sentence it printed turned out not to match the table
printed directly above it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from monetka.ml.diagnostics import RELATIVE_HORIZON_FLOOR, recommend_horizon


def frame(pairs: list[tuple[int, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"period_no": period, "accuracy": accuracy} for period, accuracy in pairs])


class TestRecommendHorizon:
    def test_reproduces_the_shipped_horizon_on_measured_data(self) -> None:
        """The real numbers from a container run must select BEHAVIOUR_MAX_PERIOD.

        If this stops holding, either the simulator changed or the horizon is
        stale — both are things to look at before shipping a model.
        """
        from monetka.ml import features as feat

        measured = frame(
            [
                (3, 0.769),
                (4, 0.831),
                (5, 0.796),
                (6, 0.671),
                (7, 0.591),
                (8, 0.600),
                (9, 0.511),
                (10, 0.462),
            ]
        )
        best, floor, recommended = recommend_horizon(measured)
        assert best == pytest.approx(0.831)
        assert floor == pytest.approx(0.831 * RELATIVE_HORIZON_FLOOR)
        assert recommended == feat.BEHAVIOUR_MAX_PERIOD == 5

    def test_a_later_recovery_does_not_extend_the_horizon(self) -> None:
        """One good period after a bad one cannot rescue the range.

        The model would still have to answer for the period that failed in
        between, so the horizon stops at the first fall-through. Taking the
        maximum passing period instead would have extended it to 8 here.
        """
        recovering = frame([(3, 0.90), (4, 0.88), (5, 0.50), (6, 0.45), (7, 0.40), (8, 0.89)])
        _, _, recommended = recommend_horizon(recovering)
        assert recommended == 4

    def test_a_flat_table_keeps_every_period(self) -> None:
        flat = frame([(3, 0.80), (4, 0.80), (5, 0.80), (6, 0.80)])
        _, _, recommended = recommend_horizon(flat)
        assert recommended == 6

    def test_an_immediate_collapse_keeps_only_the_first_period(self) -> None:
        collapsing = frame([(3, 0.95), (4, 0.30), (5, 0.20)])
        _, _, recommended = recommend_horizon(collapsing)
        assert recommended == 3

    def test_row_order_does_not_matter(self) -> None:
        """The table arrives from a groupby; its order is not guaranteed."""
        shuffled = frame([(6, 0.671), (3, 0.769), (5, 0.796), (4, 0.831)])
        _, _, recommended = recommend_horizon(shuffled)
        assert recommended == 5

    def test_a_single_period_is_its_own_horizon(self) -> None:
        _, _, recommended = recommend_horizon(frame([(3, 0.42)]))
        assert recommended == 3


class TestDiagnosticsAreReachable:
    def test_the_cli_exposes_them(self) -> None:
        """They lived behind `python -m`, which nobody following the README runs."""
        from typer.testing import CliRunner

        from monetka.cli import app

        result = CliRunner().invoke(app, ["diagnose", "--help"])
        assert result.exit_code == 0
        assert "behaviour-horizon" in result.stdout

    def test_an_unknown_diagnostic_is_rejected(self) -> None:
        from typer.testing import CliRunner

        from monetka.cli import app

        result = CliRunner().invoke(app, ["diagnose", "not-a-diagnostic"])
        assert result.exit_code == 2

    def test_the_query_is_ordered(self) -> None:
        """Without ORDER BY the train/test split moves between runs.

        DuckDB makes no ordering promise, and a parallel scan really does return
        rows differently. Evidence that changes when you re-run it is not
        evidence — the same bug was fixed in `features.py` earlier.
        """
        from pathlib import Path

        from monetka.common.config import REPO_ROOT

        source = Path(REPO_ROOT / "src" / "monetka" / "ml" / "diagnostics.py").read_text(
            encoding="utf-8"
        )
        assert "ORDER BY profile_pseudo_id, period_no" in source
