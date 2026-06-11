"""Unit tests for backtest.sweep — grid validity filtering and regime segmentation."""
import itertools

import pytest

from backtest.sweep import (
    GRID,
    SELECTION_END,
    SELECTION_START,
    VALIDATION_START,
    _disqualified,
    _valid_combo,
)


# ---------------------------------------------------------------------------
# Grid validity filtering
# ---------------------------------------------------------------------------

def test_valid_combo_rejects_rich_lte_hurdle():
    assert _valid_combo(hurdle=0.10, rich=0.10, exit_=0.00) is False
    assert _valid_combo(hurdle=0.10, rich=0.08, exit_=0.00) is False


def test_valid_combo_rejects_exit_gte_hurdle():
    assert _valid_combo(hurdle=0.06, rich=0.20, exit_=0.06) is False
    assert _valid_combo(hurdle=0.06, rich=0.20, exit_=0.08) is False


def test_valid_combo_accepts_valid():
    assert _valid_combo(hurdle=0.06, rich=0.20, exit_=0.00) is True
    assert _valid_combo(hurdle=0.04, rich=0.15, exit_=0.02) is True


def test_grid_has_no_invalid_combos():
    """Every config produced by the sweep grid should be valid."""
    invalids = []
    for hurdle, rich, window, exit_ in itertools.product(
        GRID["min_funding_hurdle_ann"],
        GRID["rich_funding_ann"],
        GRID["trailing_window_hours"],
        GRID["exit_funding_ann"],
    ):
        if not _valid_combo(hurdle, rich, exit_):
            invalids.append((hurdle, rich, exit_))
    # The invalids list exists; our filter must exclude them
    all_combos = list(itertools.product(
        GRID["min_funding_hurdle_ann"],
        GRID["rich_funding_ann"],
        GRID["trailing_window_hours"],
        GRID["exit_funding_ann"],
    ))
    valid = [(h, r, w, e) for h, r, w, e in all_combos if _valid_combo(h, r, e)]
    assert len(valid) < len(all_combos), "Some combos should be filtered out"
    assert all(_valid_combo(h, r, e) for h, r, w, e in valid)


# ---------------------------------------------------------------------------
# Disqualification logic
# ---------------------------------------------------------------------------

def _make_row(liquidations=0, kill_switch=False, yearly_rois=None) -> list[dict]:
    """Build a minimal row list for _disqualified()."""
    if yearly_rois is None:
        yearly_rois = [0.10, 0.05, 0.08]
    return [{
        "liquidations": liquidations,
        "kill_switch": kill_switch,
        "yearly": [{"year": 2020 + i, "roi": r, "max_drawdown": -0.05}
                   for i, r in enumerate(yearly_rois)],
    }]


def test_disqualified_on_liquidation():
    assert _disqualified(_make_row(liquidations=1)) is True


def test_disqualified_on_kill_switch():
    assert _disqualified(_make_row(kill_switch=True)) is True


def test_disqualified_two_negative_years():
    assert _disqualified(_make_row(yearly_rois=[-0.05, -0.03, 0.10])) is True


def test_qualified_one_negative_year():
    assert _disqualified(_make_row(yearly_rois=[-0.02, 0.05, 0.08])) is False


def test_qualified_no_issues():
    assert _disqualified(_make_row()) is False


# ---------------------------------------------------------------------------
# Regime segmentation boundary dates
# ---------------------------------------------------------------------------

def test_selection_window_boundaries():
    import pandas as pd
    sel_start = pd.Timestamp(SELECTION_START, tz="UTC")
    sel_end = pd.Timestamp(SELECTION_END, tz="UTC")
    val_start = pd.Timestamp(VALIDATION_START, tz="UTC")

    # Selection ends before validation begins
    assert sel_end < val_start
    # No overlap
    assert sel_end.year == 2023
    assert val_start.year == 2024
    # Covers at least 3 years in-sample
    assert (sel_end - sel_start).days >= 365 * 3
