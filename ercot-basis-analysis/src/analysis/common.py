"""Helpers shared by the analysis modules.

Column names in ERCOT feeds vary between report revisions. Rather than
hardcode one spelling and silently produce empty results when it changes,
resolve_column probes candidates and raises a clear error naming what it saw.
"""

from __future__ import annotations

import pandas as pd


def resolve_column(df: pd.DataFrame, candidates: list[str], purpose: str) -> str:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    raise KeyError(
        f"Could not find a column for {purpose}. Tried {candidates}; "
        f"available columns are {list(df.columns)}. Update the candidate list "
        "rather than guessing."
    )


def require(df: pd.DataFrame, columns: list[str], context: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise KeyError(f"{context}: missing required columns {missing}")
