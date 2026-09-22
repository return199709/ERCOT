"""Analysis 4: negative price incidence by node and month."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import require


def by_node(prices: pd.DataFrame, value_col: str = "SPP") -> pd.DataFrame:
    require(prices, ["Location", value_col], "negative_prices.by_node")
    df = prices.dropna(subset=[value_col])
    out = df.groupby("Location", as_index=False).agg(
        intervals=(value_col, "size"),
        negative_intervals=(value_col, lambda s: int((s < 0).sum())),
        min_price=(value_col, "min"),
    )
    out["negative_share"] = out["negative_intervals"] / out["intervals"]
    return out.sort_values("negative_share", ascending=False).reset_index(drop=True)


def by_node_month(prices: pd.DataFrame, value_col: str = "SPP") -> pd.DataFrame:
    require(prices, ["Location", "month", value_col], "negative_prices.by_node_month")
    df = prices.dropna(subset=[value_col])
    out = df.groupby(["Location", "month"], as_index=False).agg(
        intervals=(value_col, "size"),
        negative_intervals=(value_col, lambda s: int((s < 0).sum())),
    )
    out["negative_share"] = out["negative_intervals"] / out["intervals"]
    return out


def system_summary(prices: pd.DataFrame, value_col: str = "SPP") -> dict:
    df = prices.dropna(subset=[value_col])
    if df.empty:
        return {"intervals": 0, "negative_intervals": 0, "negative_share": 0.0}
    negative = int((df[value_col] < 0).sum())
    return {
        "intervals": len(df),
        "negative_intervals": negative,
        "negative_share": negative / len(df),
        "min_price": float(df[value_col].min()),
    }
