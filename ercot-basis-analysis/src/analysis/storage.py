"""Analysis 7: storage arbitrage screen.

Average daily spread between the mean of the highest-priced hours and the
mean of the lowest-priced hours -- a first-order screen for where a
4-hour battery would have earned the most, before efficiency and cycling
limits.
"""

from __future__ import annotations

import pandas as pd

from src.config import STORAGE_TOP_HOURS
from src.analysis.common import require


def daily_spread(prices: pd.DataFrame, value_col: str = "SPP",
                 hours: int = STORAGE_TOP_HOURS) -> pd.DataFrame:
    """Top-N minus bottom-N hour spread per node-day."""
    require(prices, ["Location", "local_date", value_col], "storage.daily_spread")

    def _spread(series: pd.Series) -> float:
        clean = series.dropna()
        if len(clean) < hours * 2:
            # Not enough hours to form two disjoint windows: report nothing
            # rather than a spread computed from overlapping hours.
            return float("nan")
        ordered = clean.sort_values()
        return ordered.tail(hours).mean() - ordered.head(hours).mean()

    out = (
        prices.groupby(["Location", "local_date"])[value_col]
        .apply(_spread)
        .reset_index(name="spread")
    )
    return out


def by_node(prices: pd.DataFrame, value_col: str = "SPP",
            hours: int = STORAGE_TOP_HOURS) -> pd.DataFrame:
    """Average daily spread per node, ranked best first."""
    daily = daily_spread(prices, value_col, hours)
    out = daily.groupby("Location", as_index=False).agg(
        days=("spread", "size"),
        mean_spread=("spread", "mean"),
        median_spread=("spread", "median"),
        p95_spread=("spread", lambda s: s.quantile(0.95)),
    )
    return out.sort_values("mean_spread", ascending=False).reset_index(drop=True)
