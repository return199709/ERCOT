"""Analysis 6: day-ahead versus real-time spread and persistent bias."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import require

# A node is flagged as persistently biased when the mean spread is large
# relative to its own variability -- i.e. the bias is unlikely to be noise.
BIAS_T_THRESHOLD = 2.0


def by_node(spread_df: pd.DataFrame) -> pd.DataFrame:
    """Mean, volatility and a bias flag for the DA-RT spread per node."""
    require(spread_df, ["Location", "da_rt_spread"], "da_rt.by_node")

    out = spread_df.groupby("Location", as_index=False).agg(
        n=("da_rt_spread", "size"),
        mean_spread=("da_rt_spread", "mean"),
        std_spread=("da_rt_spread", "std"),
        median_spread=("da_rt_spread", "median"),
    )
    # Standard error of the mean; t = mean / se.
    se = out["std_spread"] / out["n"].pow(0.5)
    out["t_stat"] = (out["mean_spread"] / se).where(se > 0)
    out["persistent_bias"] = out["t_stat"].abs() > BIAS_T_THRESHOLD
    out["bias_direction"] = pd.NA
    out.loc[out["persistent_bias"] & (out["mean_spread"] > 0), "bias_direction"] = "DA_over_RT"
    out.loc[out["persistent_bias"] & (out["mean_spread"] < 0), "bias_direction"] = "RT_over_DA"
    return out.sort_values("mean_spread").reset_index(drop=True)


def by_node_month(spread_df: pd.DataFrame) -> pd.DataFrame:
    require(spread_df, ["Location", "da_rt_spread", "hour_start_utc"],
            "da_rt.by_node_month")
    df = spread_df.copy()
    df["month"] = pd.to_datetime(df["hour_start_utc"], utc=True).dt.strftime("%Y-%m")
    return df.groupby(["Location", "month"], as_index=False).agg(
        n=("da_rt_spread", "size"),
        mean_spread=("da_rt_spread", "mean"),
        std_spread=("da_rt_spread", "std"),
    )
