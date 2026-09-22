"""Analysis 2: year-over-year basis trend and widening-negative flags."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import require

# A node is flagged when its mean basis is negative and fell by at least this
# many $/MWh year over year.
WIDENING_THRESHOLD = 1.0


def yoy_by_node(basis_df: pd.DataFrame) -> pd.DataFrame:
    """Mean basis per node per year, with the year-over-year change."""
    require(basis_df, ["Location", "basis", "year"], "trend.yoy_by_node")

    yearly = basis_df.groupby(["Location", "year"], as_index=False).agg(
        n=("basis", "size"), mean_basis=("basis", "mean")
    )
    yearly = yearly.sort_values(["Location", "year"])
    yearly["prev_mean_basis"] = yearly.groupby("Location")["mean_basis"].shift(1)
    yearly["yoy_change"] = yearly["mean_basis"] - yearly["prev_mean_basis"]
    return yearly.reset_index(drop=True)


def widening_negative(basis_df: pd.DataFrame,
                      threshold: float = WIDENING_THRESHOLD) -> pd.DataFrame:
    """Nodes whose basis is negative and became materially more negative.

    Requires at least two years of data for a node; nodes with one year are
    excluded rather than reported as unchanged.
    """
    yearly = yoy_by_node(basis_df)
    latest = yearly.dropna(subset=["yoy_change"])
    flagged = latest[
        (latest["mean_basis"] < 0) & (latest["yoy_change"] <= -threshold)
    ]
    return flagged.sort_values("yoy_change").reset_index(drop=True)
