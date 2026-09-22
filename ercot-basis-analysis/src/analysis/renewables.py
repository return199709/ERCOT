"""Analysis 3: basis versus wind and solar output.

Focused on West and Panhandle, where transmission limits and heavy wind
build-out are the usual explanation for persistent negative basis.
"""

from __future__ import annotations

import pandas as pd

from src.analysis.common import resolve_column

GENERATION_CANDIDATES = [
    "Actual", "actual", "GEN_SYSTEM_WIDE", "Actual System Wide",
    "System Wide Actual", "generation_mw",
]
TIME_CANDIDATES = ["interval_start_utc", "Interval Start", "Timestamp"]


def prepare_generation(df: pd.DataFrame, label: str,
                       region_column: str | None = None,
                       region: str | None = None) -> pd.DataFrame:
    """Reduce a wind/solar feed to (hour_start_utc, <label>_mw)."""
    if df.empty:
        return pd.DataFrame(columns=["hour_start_utc", f"{label}_mw"])

    time_col = resolve_column(df, TIME_CANDIDATES, f"{label} timestamp")
    gen_col = resolve_column(df, GENERATION_CANDIDATES, f"{label} generation")

    work = df
    if region_column and region:
        work = work[work[region_column].astype(str).str.contains(region, case=False,
                                                                 na=False)]
    out = pd.DataFrame({
        "hour_start_utc": pd.to_datetime(work[time_col], utc=True).dt.floor("h"),
        f"{label}_mw": pd.to_numeric(work[gen_col], errors="coerce"),
    })
    return out.groupby("hour_start_utc", as_index=False).mean()


def join_basis_to_generation(basis_df: pd.DataFrame,
                             *generation: pd.DataFrame) -> pd.DataFrame:
    """Attach hourly generation series to the hourly basis table."""
    out = basis_df.copy()
    out["hour_start_utc"] = pd.to_datetime(
        out["interval_start_utc"], utc=True
    ).dt.floor("h")
    for gen in generation:
        if not gen.empty:
            out = out.merge(gen, on="hour_start_utc", how="left")
    return out


def correlations(joined: pd.DataFrame,
                 generation_cols: list[str] | None = None) -> pd.DataFrame:
    """Pearson correlation of basis against each generation series, per node."""
    generation_cols = generation_cols or [
        c for c in joined.columns if c.endswith("_mw")
    ]
    if not generation_cols:
        return pd.DataFrame(columns=["Location", "series", "correlation", "n"])

    rows = []
    for location, group in joined.groupby("Location"):
        for col in generation_cols:
            pair = group[["basis", col]].dropna()
            # Correlation on fewer than 30 pairs is not worth reporting.
            if len(pair) < 30 or pair[col].nunique() < 2:
                continue
            rows.append({
                "Location": location,
                "series": col,
                "correlation": pair["basis"].corr(pair[col]),
                "n": len(pair),
            })
    if not rows:
        # An empty list yields a column-less frame, so build the typed shape
        # explicitly rather than letting the sort below raise.
        return pd.DataFrame(columns=["Location", "series", "correlation", "n"])
    return pd.DataFrame(rows).sort_values("correlation").reset_index(drop=True)
