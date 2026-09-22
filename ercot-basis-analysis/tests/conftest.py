"""Shared synthetic fixtures.

EVERYTHING IN THIS FILE IS SYNTHETIC TEST DATA. It is fabricated to exercise
code paths and must never be used for, or reported as, analysis results.
Real findings come only from ingested ERCOT data.
"""

import pandas as pd
import pytest

from src.config import ERCOT_TZ

SYNTHETIC = True  # explicit marker; asserted by test_no_synthetic_leakage

# A resource node in the West zone and one in the North zone.
ZONE_MAP = {"SYNTH_NODE_W": "LZ_WEST", "SYNTH_NODE_N": "LZ_NORTH"}


def _intervals(start="2025-06-11", hours=24):
    idx = pd.date_range(f"{start} 00:00", periods=hours, freq="h", tz=ERCOT_TZ)
    return idx.tz_convert("UTC")


@pytest.fixture
def synthetic_dam_prices() -> pd.DataFrame:
    """Hourly DAM prices: 2 hubs, 1 load zone, 2 resource nodes."""
    utc = _intervals()
    rows = []
    for i, ts in enumerate(utc):
        base = 30.0 + i  # deterministic ramp
        rows += [
            {"Location": "HB_NORTH", "interval_start_utc": ts, "SPP": base},
            {"Location": "HB_WEST", "interval_start_utc": ts, "SPP": base - 5.0},
            {"Location": "LZ_WEST", "interval_start_utc": ts, "SPP": base - 4.0},
            # West node sits 10 below its hub -> basis = -10
            {"Location": "SYNTH_NODE_W", "interval_start_utc": ts, "SPP": base - 15.0},
            # North node sits 2 above its hub -> basis = +2
            {"Location": "SYNTH_NODE_N", "interval_start_utc": ts, "SPP": base + 2.0},
        ]
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_rtm_prices() -> pd.DataFrame:
    """15-minute RTM prices averaging to DAM minus 3 for every node."""
    utc = pd.date_range("2025-06-11 00:00", periods=24 * 4, freq="15min",
                        tz=ERCOT_TZ).tz_convert("UTC")
    rows = []
    for i, ts in enumerate(utc):
        base = 30.0 + (i // 4)
        rows += [
            {"Location": "HB_WEST", "interval_start_utc": ts, "SPP": base - 8.0},
            {"Location": "SYNTH_NODE_W", "interval_start_utc": ts, "SPP": base - 18.0},
        ]
    return pd.DataFrame(rows)


@pytest.fixture
def zone_map() -> dict:
    return dict(ZONE_MAP)


@pytest.fixture
def synthetic_basis(synthetic_dam_prices, zone_map) -> pd.DataFrame:
    """Basis table with calendar columns attached (synthetic)."""
    from src.transform.basis import compute_basis
    from src.transform.time_utils import add_time_parts

    basis, _ = compute_basis(synthetic_dam_prices, zone_map)
    basis["Interval Start"] = pd.to_datetime(
        basis["interval_start_utc"]
    ).dt.tz_convert(ERCOT_TZ)
    return add_time_parts(basis)


@pytest.fixture
def synthetic_shadow_prices_dam() -> pd.DataFrame:
    """DAM binding constraints (synthetic)."""
    ts = pd.date_range("2025-06-11 00:00", periods=4, freq="h", tz="UTC")
    return pd.DataFrame({
        "Constraint Name": ["VALLEY_TIE", "VALLEY_TIE", "PANHANDLE_EXP", "NOT_BOUND"],
        "Interval Start": ts,
        "Shadow Price": [100.0, 50.0, 20.0, 0.0],
    })


@pytest.fixture
def synthetic_shadow_prices_sced() -> pd.DataFrame:
    """SCED binding constraints at 5-minute resolution (synthetic)."""
    ts = pd.date_range("2025-06-11 00:00", periods=12, freq="5min", tz="UTC")
    return pd.DataFrame({
        "Constraint Name": ["VALLEY_TIE"] * 12,
        "SCED Timestamp": ts,
        "Shadow Price": [60.0] * 12,
    })
