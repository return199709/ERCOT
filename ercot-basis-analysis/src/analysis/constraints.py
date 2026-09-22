"""Analysis 5: binding constraint ranking by congestion cost.

Shadow price is a $/MWh rate, and DAM intervals (1 hour) are twelve times
longer than SCED intervals (5 minutes). Summing raw shadow prices across both
markets would silently weight SCED intervals as heavily as DAM hours, so
everything is normalised to $-hours: shadow_price * interval_duration_hours.
"""

from __future__ import annotations

import pandas as pd

from src.config import TOP_CONSTRAINTS_N
from src.analysis.common import resolve_column

# Interval length by market, in hours.
DAM_INTERVAL_HOURS = 1.0
SCED_INTERVAL_HOURS = 5.0 / 60.0

CONSTRAINT_NAME_CANDIDATES = [
    "Constraint Name", "ConstraintName", "constraint_name", "Constraint",
]
SHADOW_PRICE_CANDIDATES = [
    "Shadow Price", "ShadowPrice", "shadow_price", "Max Shadow Price",
]
TIME_CANDIDATES = [
    "interval_start_utc", "Interval Start", "SCED Timestamp", "Timestamp",
]


def normalise(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Canonicalise a shadow price table to (constraint, time, price, hours)."""
    if df.empty:
        return pd.DataFrame(columns=["constraint", "time", "shadow_price",
                                     "interval_hours", "market", "cost"])

    name_col = resolve_column(df, CONSTRAINT_NAME_CANDIDATES, "constraint name")
    price_col = resolve_column(df, SHADOW_PRICE_CANDIDATES, "shadow price")
    time_col = resolve_column(df, TIME_CANDIDATES, "interval timestamp")

    hours = DAM_INTERVAL_HOURS if market.lower() == "dam" else SCED_INTERVAL_HOURS
    out = pd.DataFrame({
        "constraint": df[name_col].astype(str),
        "time": pd.to_datetime(df[time_col], utc=True, errors="coerce"),
        "shadow_price": pd.to_numeric(df[price_col], errors="coerce"),
    })
    out["interval_hours"] = hours
    out["market"] = market.upper()
    out = out.dropna(subset=["shadow_price", "time"])
    # A constraint is "bound" when it carries a nonzero shadow price.
    out = out[out["shadow_price"] != 0]
    out["cost"] = out["shadow_price"] * out["interval_hours"]
    return out.reset_index(drop=True)


def rank(normalised: pd.DataFrame, n: int = TOP_CONSTRAINTS_N) -> pd.DataFrame:
    """Rank constraints by total congestion cost in $-hours."""
    if normalised.empty:
        return pd.DataFrame(columns=["constraint", "total_cost", "intervals_bound",
                                     "bound_hours", "mean_shadow_price"])
    out = normalised.groupby("constraint", as_index=False).agg(
        total_cost=("cost", "sum"),
        intervals_bound=("cost", "size"),
        bound_hours=("interval_hours", "sum"),
        mean_shadow_price=("shadow_price", "mean"),
        max_shadow_price=("shadow_price", "max"),
    )
    return out.nlargest(n, "total_cost").reset_index(drop=True)


def seasonality(normalised: pd.DataFrame) -> pd.DataFrame:
    """Congestion cost by constraint and calendar month."""
    if normalised.empty:
        return pd.DataFrame(columns=["constraint", "month", "total_cost"])
    df = normalised.copy()
    df["month"] = df["time"].dt.strftime("%Y-%m")
    return df.groupby(["constraint", "month"], as_index=False).agg(
        total_cost=("cost", "sum"), intervals_bound=("cost", "size")
    )


def combined(dam: pd.DataFrame, sced: pd.DataFrame,
             n: int = TOP_CONSTRAINTS_N) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalise both markets, then rank jointly and per market."""
    parts = [normalise(dam, "dam"), normalise(sced, "sced")]
    allrows = pd.concat([p for p in parts if not p.empty], ignore_index=True) \
        if any(not p.empty for p in parts) else pd.DataFrame()
    return rank(allrows, n), allrows
