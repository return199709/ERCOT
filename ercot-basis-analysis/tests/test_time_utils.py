"""Tests for DST and peak-hour handling.

All data here is synthetic and exists only to exercise calendar logic.
"""

import pandas as pd
import pytest

from src.config import ERCOT_TZ
from src.transform.time_utils import (
    add_time_parts,
    ensure_utc,
    expected_intervals,
    is_peak,
    nerc_holidays,
)

# 2025 US DST transitions
SPRING_FORWARD = "2025-03-09"   # 23-hour day
FALL_BACK = "2025-11-02"        # 25-hour day
NORMAL_DAY = "2025-06-11"       # Wednesday


class TestExpectedIntervals:
    def test_normal_day_is_full_length(self):
        assert expected_intervals(NORMAL_DAY, 24) == 24
        assert expected_intervals(NORMAL_DAY, 96) == 96

    def test_spring_forward_day_is_one_hour_short(self):
        assert expected_intervals(SPRING_FORWARD, 24) == 23
        assert expected_intervals(SPRING_FORWARD, 96) == 92

    def test_fall_back_day_is_one_hour_long(self):
        assert expected_intervals(FALL_BACK, 24) == 25
        assert expected_intervals(FALL_BACK, 96) == 100


class TestIsPeak:
    def _local(self, stamps):
        return pd.Series(pd.to_datetime(stamps)).dt.tz_localize(ERCOT_TZ)

    def test_weekday_midday_is_peak(self):
        assert is_peak(self._local(["2025-06-11 10:00"])).iloc[0]

    def test_weekday_night_is_offpeak(self):
        assert not is_peak(self._local(["2025-06-11 03:00"])).iloc[0]

    def test_hour_boundaries(self):
        # 5x16 is hour-ending 07 through hour-ending 22. In interval-start
        # terms that is 06:00 inclusive through 22:00 exclusive.
        vals = is_peak(self._local(
            ["2025-06-11 05:59", "2025-06-11 06:00",
             "2025-06-11 21:59", "2025-06-11 22:00"]
        ))
        assert list(vals) == [False, True, True, False]

    def test_weekday_has_sixteen_peak_hours(self):
        # Regression: a [7, 21] window gave 15 hours; June 2025 showed
        # 315 on-peak hours per node, which is 21 weekdays x 15.
        stamps = [f"2025-06-11 {h:02d}:00" for h in range(24)]  # a Wednesday
        assert int(is_peak(self._local(stamps)).sum()) == 16

    def test_weekend_is_offpeak(self):
        assert not is_peak(self._local(["2025-06-14 10:00"])).iloc[0]  # Saturday

    def test_nerc_holiday_is_offpeak(self):
        # 2025-07-04 is a Friday -- a weekday that must still be off-peak.
        stamp = self._local(["2025-07-04 10:00"])
        assert stamp.iloc[0].weekday() == 4
        assert not is_peak(stamp).iloc[0]

    def test_empty_input(self):
        assert is_peak(pd.Series([], dtype="datetime64[ns, US/Central]")).empty


class TestNercHolidays:
    def test_six_holidays_per_year(self):
        days = nerc_holidays("2025-01-01", "2025-12-31")
        assert len(days) == 6


class TestEnsureUtc:
    def test_adds_utc_column_from_aware_input(self):
        df = pd.DataFrame({
            "Interval Start": pd.to_datetime(
                ["2025-06-11 10:00", "2025-06-11 11:00"]
            ).tz_localize(ERCOT_TZ)
        })
        out = ensure_utc(df)
        assert "interval_start_utc" in out
        assert str(out["interval_start_utc"].dt.tz) == "UTC"
        # 10:00 CDT == 15:00 UTC
        assert out["interval_start_utc"].iloc[0].hour == 15

    def test_missing_column_raises(self):
        with pytest.raises(KeyError):
            ensure_utc(pd.DataFrame({"wrong": [1]}))

    def test_fall_back_hour_is_distinguishable_in_utc(self):
        """The repeated 01:00 must map to two distinct UTC instants."""
        local = pd.DatetimeIndex(
            ["2025-11-02 01:00", "2025-11-02 01:00"]
        ).tz_localize(ERCOT_TZ, ambiguous=[True, False])  # CDT then CST
        out = ensure_utc(pd.DataFrame({"Interval Start": local}))
        assert out["interval_start_utc"].nunique() == 2


class TestAddTimeParts:
    def test_adds_grouping_columns(self):
        df = pd.DataFrame({
            "Interval Start": pd.to_datetime(
                ["2025-06-11 10:00"]
            ).tz_localize(ERCOT_TZ)
        })
        out = add_time_parts(df)
        assert out["hour"].iloc[0] == 10
        assert out["month"].iloc[0] == "2025-06"
        assert out["year"].iloc[0] == 2025
        assert bool(out["is_peak"].iloc[0]) is True
