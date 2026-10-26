"""Constraint dictionary: what physical element each constraint name is.

ERCOT constraint names such as `6437__F` or `MDOPHR99_A` are identifiers,
not descriptions. The shadow price feeds that this project already ingests
carry the description alongside each row: the from and to station, their
voltage levels, the limiting facility and the contingency under which the
constraint binds. This module reduces those rows to one record per
constraint so that every table that names a constraint can also say what it
is.

Nothing is fetched and nothing is inferred. Where a constraint appears with
more than one value for an attribute (a station name that changed, several
contingencies), the most frequent value is kept and the number of distinct
contingencies is reported, so the reader can see when one name has covered
more than one physical situation.
"""

from __future__ import annotations

import pandas as pd

from src.analysis.common import resolve_column
from src.analysis.constraints import CONSTRAINT_NAME_CANDIDATES

# Attribute columns as gridstatus names them. Each is optional: a feed
# revision that lacks one simply yields a dictionary without that column.
ATTRIBUTES = {
    "from_station": ["From Station", "FromStation"],
    "to_station": ["To Station", "ToStation"],
    "from_kv": ["From Station kV", "FromStationkV"],
    "to_kv": ["To Station kV", "ToStationkV"],
    "limiting_facility": ["Limiting Facility"],
    "contingency": ["Contingency Name", "ContingencyName"],
    "constraint_limit": ["Constraint Limit", "ConstraintLimit"],
    "constraint_id": ["Constraint ID", "ConstraintID", "ConstraintId"],
}

COLUMNS = [
    "constraint", "element", "from_station", "to_station", "from_kv", "to_kv",
    "limiting_facility", "top_contingency", "n_contingencies",
    "constraint_limit_min", "constraint_limit_max", "constraint_id",
    "markets", "rows",
]


def _mode(series: pd.Series):
    """Most frequent non-null value, or NA."""
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    if s.empty:
        return pd.NA
    return s.astype(str).str.strip().mode().iloc[0]


def _label(row: pd.Series) -> str:
    """A one-line human description, falling back to the bare name."""
    frm, to = row.get("from_station"), row.get("to_station")
    if pd.isna(frm) and pd.isna(to):
        return str(row["constraint"])
    parts = []
    for station, kv in ((frm, row.get("from_kv")), (to, row.get("to_kv"))):
        if pd.isna(station):
            continue
        text = str(station)
        if not pd.isna(kv):
            try:
                text += f" {float(kv):g} kV"
            except (TypeError, ValueError):
                text += f" {kv}"
        parts.append(text)
    label = " -> ".join(parts)
    facility = row.get("limiting_facility")
    if not pd.isna(facility) and str(facility) not in label:
        label += f" ({facility})"
    return label


def _normalise(df: pd.DataFrame, market: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    name_col = resolve_column(df, CONSTRAINT_NAME_CANDIDATES, "constraint name")
    out = pd.DataFrame({"constraint": df[name_col].astype(str).str.strip()})
    for key, candidates in ATTRIBUTES.items():
        col = next((c for c in candidates if c in df.columns), None)
        # Everything is carried as object so the DAM and SCED parts always
        # share dtypes: pandas warns when it concatenates an all-NA object
        # column against a numeric one, and a feed revision may lack any of
        # these attributes. Numeric use happens downstream via to_numeric.
        values = df[col].to_numpy(dtype=object) if col else [pd.NA] * len(out)
        out[key] = pd.Series(values, index=out.index, dtype="object")
    out["market"] = market.upper()
    return out


def build(dam: pd.DataFrame | None, sced: pd.DataFrame | None) -> pd.DataFrame:
    """One row per constraint name seen in either feed."""
    parts = [_normalise(dam, "dam"), _normalise(sced, "sced")]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    rows = pd.concat(parts, ignore_index=True)

    grouped = rows.groupby("constraint", sort=True)
    out = pd.DataFrame({"constraint": list(grouped.groups)})
    out = out.set_index("constraint")
    for key in ("from_station", "to_station", "from_kv", "to_kv",
                "limiting_facility", "constraint_id"):
        out[key] = grouped[key].agg(_mode)
    out["top_contingency"] = grouped["contingency"].agg(_mode)
    out["n_contingencies"] = grouped["contingency"].agg(
        lambda s: int(s.dropna().astype(str).str.strip().replace("", pd.NA)
                      .dropna().nunique())
    )
    limits = pd.to_numeric(rows["constraint_limit"], errors="coerce")
    out["constraint_limit_min"] = limits.groupby(rows["constraint"]).min()
    out["constraint_limit_max"] = limits.groupby(rows["constraint"]).max()
    out["markets"] = grouped["market"].agg(lambda s: "+".join(sorted(set(s))))
    out["rows"] = grouped.size()
    out = out.reset_index()
    out["element"] = out.apply(_label, axis=1)
    return out[COLUMNS]


def attach(df: pd.DataFrame, dictionary: pd.DataFrame, on: str = "constraint",
           out: str = "element") -> pd.DataFrame:
    """Add a human label column to any frame that names constraints.

    Unknown names get the name itself as their label, so the column is
    always populated and never silently blank.
    """
    if df is None or df.empty or on not in df.columns:
        return df
    lookup = {}
    if dictionary is not None and not dictionary.empty:
        lookup = dict(zip(dictionary["constraint"], dictionary["element"]))
    result = df.copy()
    labels = result[on].map(lookup)
    result[out] = labels.where(labels.notna(), result[on])
    # Put the label right after the name it describes.
    cols = list(result.columns)
    cols.remove(out)
    cols.insert(cols.index(on) + 1, out)
    return result[cols]
