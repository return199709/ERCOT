"""Analysis 1: basis distribution by node, month, hour and peak period."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import require
from src.config import BASIS_PERCENTILES, WORST_NODES_TOP_N

P_LOW, P_HIGH = BASIS_PERCENTILES


def _agg(group: pd.DataFrame) -> pd.Series:
    basis = group["basis"].dropna()
    if basis.empty:
        return pd.Series({"n": 0, "mean": pd.NA, "p5": pd.NA,
                          "p95": pd.NA, "std": pd.NA})
    return pd.Series({
        "n": len(basis),
        "mean": basis.mean(),
        "p5": basis.quantile(P_LOW),
        "p95": basis.quantile(P_HIGH),
        "std": basis.std(),
    })


def by_node(basis_df: pd.DataFrame) -> pd.DataFrame:
    """Overall basis statistics per node."""
    require(basis_df, ["Location", "basis"], "by_node")
    return (
        basis_df.groupby("Location", group_keys=False)
        .apply(_agg, include_groups=False)
        .reset_index()
        .sort_values("mean")
        .reset_index(drop=True)
    )


def by_node_peak(basis_df: pd.DataFrame) -> pd.DataFrame:
    """Basis split on-peak versus off-peak."""
    require(basis_df, ["Location", "basis", "is_peak"], "by_node_peak")
    out = (
        basis_df.groupby(["Location", "is_peak"], group_keys=False)
        .apply(_agg, include_groups=False)
        .reset_index()
    )
    out["period"] = out["is_peak"].map({True: "on_peak", False: "off_peak"})
    return out.drop(columns="is_peak")


def by_month(basis_df: pd.DataFrame) -> pd.DataFrame:
    require(basis_df, ["Location", "basis", "month"], "by_month")
    return (
        basis_df.groupby(["Location", "month"], group_keys=False)
        .apply(_agg, include_groups=False)
        .reset_index()
    )


def hour_month_heatmap(basis_df: pd.DataFrame,
                       location: str | None = None) -> pd.DataFrame:
    """Mean basis as an hour x month grid, for the dashboard heatmap."""
    require(basis_df, ["basis", "hour", "month"], "hour_month_heatmap")
    df = basis_df if location is None else basis_df[basis_df["Location"] == location]
    return df.pivot_table(index="hour", columns="month", values="basis",
                          aggfunc="mean")


def worst_nodes(basis_df: pd.DataFrame, n: int = WORST_NODES_TOP_N) -> pd.DataFrame:
    """The n nodes with the most negative mean basis."""
    stats = by_node(basis_df)
    return stats.nsmallest(n, "mean").reset_index(drop=True)
