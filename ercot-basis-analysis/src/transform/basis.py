"""Basis calculation: node price minus reference hub price.

Joins are always on `interval_start_utc`, never on local time, so the
fall-back DST hour cannot collide.
"""

from __future__ import annotations

import pandas as pd

from src.config import REFERENCE_HUBS
from src.transform.mapping import RESOURCE_NODE, assign_hub, classify_location


def compute_basis(
    prices: pd.DataFrame,
    zone_map: dict[str, str] | None = None,
    value_col: str = "SPP",
) -> tuple[pd.DataFrame, list[str]]:
    """Return (basis_table, unmapped_nodes).

    `basis` is against the node's assigned hub. `basis_vs_<HUB>` columns are
    also produced for every reference hub, so the analysis can be re-cut
    against a different reference without re-ingesting.
    """
    required = {"Location", "interval_start_utc", value_col}
    missing = required - set(prices.columns)
    if missing:
        raise KeyError(f"prices missing columns: {sorted(missing)}")

    df = prices.copy()
    df["location_class"] = df["Location"].map(classify_location)

    hub_wide = (
        df[df["Location"].isin(REFERENCE_HUBS)]
        .pivot_table(index="interval_start_utc", columns="Location",
                     values=value_col, aggfunc="mean")
    )

    nodes = df[df["location_class"] == RESOURCE_NODE].copy()
    if nodes.empty:
        return nodes.assign(basis=pd.Series(dtype=float)), []

    nodes["assigned_hub"], unmapped = assign_hub(nodes["Location"], zone_map)
    out = nodes.merge(hub_wide, on="interval_start_utc", how="left",
                      suffixes=("", "_hub"))

    for hub in REFERENCE_HUBS:
        if hub in hub_wide.columns:
            out[f"basis_vs_{hub}"] = out[value_col] - out[hub]

    # Basis against the node's own assigned hub.
    def _own_hub_price(row):
        hub = row["assigned_hub"]
        if pd.isna(hub) or hub not in hub_wide.columns:
            return pd.NA
        return row.get(hub, pd.NA)

    out["assigned_hub_price"] = out.apply(_own_hub_price, axis=1)
    out["basis"] = pd.to_numeric(out[value_col], errors="coerce") - pd.to_numeric(
        out["assigned_hub_price"], errors="coerce"
    )
    return out, unmapped


def rtm_to_hourly(rtm: pd.DataFrame, value_col: str = "SPP") -> pd.DataFrame:
    """Average 15-minute RTM prices to hourly so they align with DAM.

    A simple mean of the four intervals: ERCOT settles RT energy on a
    time-weighted basis and the intervals are equal length, so the mean is the
    correct hourly equivalent.
    """
    df = rtm.copy()
    df["hour_start_utc"] = pd.to_datetime(df["interval_start_utc"]).dt.floor("h")
    grouped = (
        df.groupby(["Location", "hour_start_utc"], as_index=False)
        .agg(rt_price=(value_col, "mean"), rt_intervals=(value_col, "size"))
    )
    return grouped


def da_rt_spread(dam: pd.DataFrame, rtm: pd.DataFrame,
                 value_col: str = "SPP") -> pd.DataFrame:
    """DA minus RT per node-hour. Positive means DA settled above RT."""
    da = dam.copy()
    da["hour_start_utc"] = pd.to_datetime(da["interval_start_utc"]).dt.floor("h")
    da = da.rename(columns={value_col: "da_price"})[
        ["Location", "hour_start_utc", "da_price"]
    ]
    rt = rtm_to_hourly(rtm, value_col)

    merged = da.merge(rt, on=["Location", "hour_start_utc"], how="inner")
    merged["da_rt_spread"] = merged["da_price"] - merged["rt_price"]
    return merged
