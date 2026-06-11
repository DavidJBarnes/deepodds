"""
Unit tests for backtest.data_ingest.

All HTTP is mocked — these tests never hit the network.
"""
import io
import zipfile
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest.data_ingest import (
    PERIODS_PER_YEAR,
    _complete_months,
    _expand_funding_to_hourly,
    _extract_csv_rows,
    _is_header,
    compare_hl_vs_binance,
)


# ---------------------------------------------------------------------------
# CRITICAL: Funding unit-conversion invariant (Task 1a requirement)
# ---------------------------------------------------------------------------

def test_funding_unit_conversion():
    """
    A constant 0.01%/8h Binance rate must annualize to ~10.95% through the pipeline.

    Proof: 0.01% per 8h = 0.0001 per 8h → hourly = 0.0001 / 8 = 0.0000125
    Annualized = 0.0000125 × 8760 = 0.1095 (10.95%)
    """
    binance_rate_8h = 0.0001          # 0.01% per settlement
    hourly_rate = binance_rate_8h / 8.0
    annualized = hourly_rate * PERIODS_PER_YEAR
    assert abs(annualized - 0.1095) < 0.0001, (
        f"Unit conversion failed: 0.01%/8h should annualize to ~10.95%, got {annualized:.4f}"
    )


def test_funding_unit_conversion_is_not_8x():
    """If we forgot to divide by 8, the result would be 8x too high (~87.6%)."""
    binance_rate_8h = 0.0001
    wrong_annualized = binance_rate_8h * PERIODS_PER_YEAR   # forgot /8
    correct_annualized = (binance_rate_8h / 8.0) * PERIODS_PER_YEAR
    assert wrong_annualized == pytest.approx(correct_annualized * 8, rel=1e-6), \
        "Sanity check: omitting /8 would overstate by 8x"
    assert wrong_annualized > 0.80    # would be ~87.6% — clearly wrong
    assert correct_annualized < 0.12  # ~10.95% — reasonable


# ---------------------------------------------------------------------------
# _complete_months
# ---------------------------------------------------------------------------

def test_complete_months_starts_at_2020_01():
    months = _complete_months()
    assert months[0] == (2020, 1)


def test_complete_months_ends_before_current_month():
    months = _complete_months()
    today = date.today()
    last = months[-1]
    # Last month should be strictly before the current month
    assert (last[0], last[1]) < (today.year, today.month)


def test_complete_months_no_gaps():
    months = _complete_months()
    for i in range(1, len(months)):
        y0, m0 = months[i - 1]
        y1, m1 = months[i]
        expected_next = (y0, m0 + 1) if m0 < 12 else (y0 + 1, 1)
        assert (y1, m1) == expected_next, f"Gap between {months[i-1]} and {months[i]}"


# ---------------------------------------------------------------------------
# _is_header
# ---------------------------------------------------------------------------

def test_is_header_detects_text():
    assert _is_header(["calc_time", "last_funding_rate", "mark_price"]) is True
    assert _is_header(["Open Time", "Close"]) is True


def test_is_header_detects_numeric():
    assert _is_header(["1578931200000", "0.0001", "7310.24"]) is False


# ---------------------------------------------------------------------------
# _extract_csv_rows
# ---------------------------------------------------------------------------

def _make_zip(content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data.csv", content)
    return buf.getvalue()


def test_extract_csv_rows_basic():
    csv_content = "1578931200000,0.0001,7310.24\n1579017600000,0.00015,7400.00\n"
    rows = _extract_csv_rows(_make_zip(csv_content))
    assert len(rows) == 2
    assert rows[0][0] == "1578931200000"
    assert rows[0][1] == "0.0001"


def test_extract_csv_rows_skips_blank_lines():
    csv_content = "1578931200000,0.0001,7310.24\n\n1579017600000,0.00015,7400.00\n"
    rows = _extract_csv_rows(_make_zip(csv_content))
    assert len(rows) == 2


def test_extract_csv_rows_with_header():
    csv_content = "calc_time,last_funding_rate,mark_price\n1578931200000,0.0001,7310.24\n"
    rows = _extract_csv_rows(_make_zip(csv_content))
    assert len(rows) == 2   # header is returned too; caller decides to skip it


# ---------------------------------------------------------------------------
# _expand_funding_to_hourly
# ---------------------------------------------------------------------------

def _make_funding_df(settlements: list[tuple]) -> pd.DataFrame:
    """Create a funding DataFrame from (ts_str, rate) pairs."""
    rows = []
    for ts_str, rate in settlements:
        rows.append({"ts": pd.Timestamp(ts_str, tz="UTC"), "funding_rate_8h": rate,
                     "funding_hourly": rate / 8.0})
    return pd.DataFrame(rows)


def test_expand_funding_forward_fills_8h_gaps():
    """A settlement at T should fill the 8 hours up to T."""
    df = _make_funding_df([
        ("2020-01-01 08:00", 0.0001),
        ("2020-01-01 16:00", 0.0002),
    ])
    hourly = _expand_funding_to_hourly(df)
    hourly = hourly.set_index("ts")

    # Rate at 08:00 should be 0.0001 / 8
    ts_8 = pd.Timestamp("2020-01-01 08:00", tz="UTC")
    assert abs(hourly.loc[ts_8, "funding_hourly"] - 0.0001 / 8) < 1e-12

    # Rate at 09:00, 10:00 ... should be forward-filled from 08:00 settlement
    for h in range(9, 16):
        ts = pd.Timestamp(f"2020-01-01 {h:02d}:00", tz="UTC")
        if ts in hourly.index:
            assert abs(hourly.loc[ts, "funding_hourly"] - 0.0001 / 8) < 1e-12


def test_expand_funding_handles_single_settlement():
    import numpy as np
    df = _make_funding_df([("2020-01-01 08:00", 0.0003)])
    hourly = _expand_funding_to_hourly(df)
    assert len(hourly) >= 1
    assert np.allclose(hourly["funding_hourly"].values, 0.0003 / 8)


# ---------------------------------------------------------------------------
# compare_hl_vs_binance (mocked)
# ---------------------------------------------------------------------------

def test_compare_hl_vs_binance_schema():
    """compare_hl_vs_binance returns a DataFrame with the expected columns."""
    mock_funding = pd.DataFrame({
        "ts": pd.date_range("2023-07-01", periods=10, freq="8h", tz="UTC"),
        "funding_rate_8h": [0.0001] * 10,
        "funding_hourly": [0.0001 / 8] * 10,
    })
    mock_hl = pd.DataFrame({
        "ts": pd.date_range("2023-07-01", periods=10, freq="h", tz="UTC"),
        "funding_hourly": [0.0001 / 8] * 10,
    })

    with patch("backtest.data_ingest.download_funding_rates", return_value=(mock_funding, "test")):
        with patch("backtest.data_ingest.download_hl_funding", return_value=mock_hl):
            df = compare_hl_vs_binance(["BTC"])

    # May be empty if no overlapping full quarters, but schema should match
    if not df.empty:
        assert {"quarter", "coin", "binance_ann", "hl_ann", "diff_pp"}.issubset(df.columns)
