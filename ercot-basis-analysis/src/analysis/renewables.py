"""Analysis 3: basis versus wind and solar output.

Focused on West and Panhandle, where transmission limits and heavy wind
build-out are the usual explanation for persistent negative basis.
"""

from __future__ import annotations

import pandas as pd

from src.analysis.common import resolve_column
from src.config import GENERATION_PREFIX

TIME_CANDIDATES = ["interval_start_utc", "Interval Start", "Timestamp"]


def normalise_region(region: str) -> str:
    """'SYSTEM WIDE' -> 'system_wide', 'FarWest' -> 'farwest'."""
    return "_".join(region.lower().split())


def generation_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map region -> column for the actual-generation columns only.

    Both feeds are wide, with a `GEN <REGION>` column per region. The
    `COP HSL <REGION>` columns alongside them are High Sustained Limit, i.e.
    available capacity, not output -- correlating basis against capacity
    instead of generation would be a silent and badly wrong analysis, so only
    the GEN prefix is matched.
    """
    return {
        col[len(GENERATION_PREFIX):].strip(): col
        for col in df.columns
        if col.startswith(GENERATION_PREFIX)
    }


def prepare_generation(df: pd.DataFrame, fuel: str,
                       regions: list[str] | None = None) -> pd.DataFrame:
    """Reduce a wide wind/solar feed to hourly generation per region.

    Returns `hour_start_utc` plus one `<fuel>_<region>_mw` column per region.
    Unknown region names are reported rather than silently dropped: a renamed
    ERCOT region would otherwise quietly remove a series from the analysis.
    """
    if df.empty:
        return pd.DataFrame(columns=["hour_start_utc"])

    time_col = resolve_column(df, TIME_CANDIDATES, f"{fuel} timestamp")
    available = generation_columns(df)
    if not available:
        raise KeyError(
            f"No '{GENERATION_PREFIX}<REGION>' columns found in the {fuel} "
            f"feed. Available columns: {sorted(df.columns)[:15]}. The feed "
            "layout has changed; do not substitute a capacity column."
        )

    if regions is None:
        selected = available
    else:
        selected = {r: c for r, c in available.items() if r in regions}
        missing = [r for r in regions if r not in available]
        if missing:
            raise KeyError(
                f"{fuel} regions {missing} are not in this feed. Present: "
                f"{sorted(available)}. Wind and solar use different "
                "geographies -- check src/config.py rather than guessing."
            )

    out = pd.DataFrame({
        "hour_start_utc": pd.to_datetime(df[time_col], utc=True).dt.floor("h")
    })
    for region, col in selected.items():
        out[f"{fuel}_{normalise_region(region)}_mw"] = pd.to_numeric(
            df[col], errors="coerce"
        )
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
