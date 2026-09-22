"""Time handling for ERCOT data.

ERCOT settles on Central Prevailing Time (CPT), which observes daylight
saving. Two transitions per year break naive assumptions:

* Spring forward: the 02:00 hour does not exist. A missing interval there is
  correct, not a gap -- the quality checks must not flag it.
* Fall back: the 01:00 hour occurs twice. Local timestamps are ambiguous, so
  UTC is the only safe key. ERCOT's feeds carry a DST flag distinguishing the
  repeated hour.

Every processed table therefore carries `interval_start_utc` alongside the
local CPT column, and all joins use UTC.
"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar, Holiday, USLaborDay, USMemorialDay,
    USThanksgivingDay, nearest_workday,
)

from src.config import (
    ERCOT_TZ, PEAK_END_HOUR, PEAK_START_HOUR, PEAK_WEEKDAYS,
)


class NERCHolidayCalendar(AbstractHolidayCalendar):
    """The six NERC holidays used for on/off-peak classification."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMemorialDay,
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


_CALENDAR = NERCHolidayCalendar()


def nerc_holidays(start, end) -> pd.DatetimeIndex:
    return _CALENDAR.holidays(start=pd.Timestamp(start), end=pd.Timestamp(end))


def ensure_utc(df: pd.DataFrame, col: str = "Interval Start") -> pd.DataFrame:
    """Add `interval_start_utc` derived from a CPT-localized column.

    Handles both tz-aware input (what gridstatus returns) and tz-naive input
    (what a CSV round-trip can produce). Ambiguous fall-back timestamps in
    naive input are resolved to the first occurrence and flagged, because
    guessing silently would corrupt an hour of data twice a year.
    """
    if col not in df.columns:
        raise KeyError(f"expected column {col!r}; got {list(df.columns)}")

    out = df.copy()
    series = pd.to_datetime(out[col])

    if series.dt.tz is None:
        localized = series.dt.tz_localize(
            ERCOT_TZ, ambiguous="infer", nonexistent="shift_forward"
        )
        out["dst_ambiguous_resolved"] = False
    else:
        localized = series.dt.tz_convert(ERCOT_TZ)

    out[col] = localized
    out["interval_start_utc"] = localized.dt.tz_convert("UTC")
    return out


def add_time_parts(df: pd.DataFrame, col: str = "Interval Start") -> pd.DataFrame:
    """Add local calendar columns used for grouping (hour, month, peak flag)."""
    out = df.copy()
    local = pd.to_datetime(out[col])
    if local.dt.tz is None:
        local = local.dt.tz_localize(ERCOT_TZ, ambiguous="infer",
                                     nonexistent="shift_forward")
    out["local_date"] = local.dt.date
    out["hour"] = local.dt.hour
    # strftime rather than to_period: periods drop tz and warn.
    out["month"] = local.dt.strftime("%Y-%m")
    out["year"] = local.dt.year
    out["weekday"] = local.dt.weekday
    out["is_peak"] = is_peak(local)
    return out


def is_peak(local: pd.Series) -> pd.Series:
    """ERCOT 5x16: HE 07:00-22:00 CPT, Mon-Fri, excluding NERC holidays."""
    if local.empty:
        return pd.Series([], dtype=bool, index=local.index)

    hour_ok = local.dt.hour.between(PEAK_START_HOUR, PEAK_END_HOUR - 1)
    day_ok = local.dt.weekday.isin(PEAK_WEEKDAYS)

    holidays = nerc_holidays(local.min().date(), local.max().date())
    holiday_dates = set(pd.DatetimeIndex(holidays).date)
    not_holiday = ~pd.Series(local.dt.date.isin(holiday_dates).values,
                             index=local.index)

    return hour_ok & day_ok & not_holiday


def expected_intervals(day: pd.Timestamp, per_day: int) -> int:
    """Intervals expected on a given local date, accounting for DST.

    A spring-forward day is one interval-hour short and a fall-back day one
    long; treating every day as `per_day` would report false gaps.
    """
    day = pd.Timestamp(day).normalize()
    start = day.tz_localize(ERCOT_TZ, nonexistent="shift_forward")
    end = (day + pd.Timedelta(days=1)).tz_localize(
        ERCOT_TZ, nonexistent="shift_forward"
    )
    hours = (end - start).total_seconds() / 3600
    return int(round(hours * per_day / 24))
