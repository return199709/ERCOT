"""Data quality checks.

Guiding rule: detect and report, never repair. Gaps are surfaced so analyses
can exclude the affected node-days explicitly; they are never interpolated,
forward-filled, or zero-filled, because a silently patched price series
produces confident and wrong basis numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.config import ERCOT_TZ, QUALITY_REPORTS
from src.transform.time_utils import expected_intervals


@dataclass
class QualityReport:
    dataset: str
    rows: int = 0
    duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    gaps: pd.DataFrame = field(default_factory=pd.DataFrame)
    name_changes: dict[str, list[str]] = field(default_factory=dict)
    null_prices: int = 0

    @property
    def clean(self) -> bool:
        return (
            self.duplicates.empty
            and self.gaps.empty
            and not any(self.name_changes.values())
            and self.null_prices == 0
        )


def find_duplicates(df: pd.DataFrame,
                    keys: tuple[str, ...] = ("Location", "interval_start_utc")
                    ) -> pd.DataFrame:
    """Rows sharing a (location, interval) key -- these must be unique."""
    missing = [k for k in keys if k not in df.columns]
    if missing:
        raise KeyError(f"missing key columns: {missing}")
    dupe_mask = df.duplicated(subset=list(keys), keep=False)
    if not dupe_mask.any():
        return pd.DataFrame(columns=list(keys) + ["n"])
    return (
        df[dupe_mask].groupby(list(keys), as_index=False)
        .size().rename(columns={"size": "n"})
    )


def find_gaps(df: pd.DataFrame, intervals_per_day: int,
              value_col: str = "SPP") -> pd.DataFrame:
    """Per location-day, compare observed interval count to the DST-aware expectation."""
    if df.empty:
        return pd.DataFrame(columns=["Location", "local_date", "observed",
                                     "expected", "missing"])
    work = df.copy()
    local = pd.to_datetime(work["interval_start_utc"]).dt.tz_convert(ERCOT_TZ)
    work["local_date"] = local.dt.date

    observed = (
        work.groupby(["Location", "local_date"], as_index=False)
        .agg(observed=(value_col, "size"))
    )
    observed["expected"] = observed["local_date"].map(
        lambda d: expected_intervals(pd.Timestamp(d), intervals_per_day)
    )
    observed["missing"] = observed["expected"] - observed["observed"]
    return observed[observed["missing"] != 0].reset_index(drop=True)


def find_name_changes(df: pd.DataFrame, month_col: str = "month",
                      location_col: str = "Location") -> dict[str, list[str]]:
    """Settlement points that appear or disappear between consecutive months."""
    if month_col not in df.columns or df.empty:
        return {"appeared": [], "disappeared": []}

    months = sorted(df[month_col].dropna().unique())
    if len(months) < 2:
        return {"appeared": [], "disappeared": []}

    appeared: set[str] = set()
    disappeared: set[str] = set()
    for prev, curr in zip(months, months[1:]):
        before = set(df.loc[df[month_col] == prev, location_col])
        after = set(df.loc[df[month_col] == curr, location_col])
        appeared |= after - before
        disappeared |= before - after
    return {"appeared": sorted(appeared), "disappeared": sorted(disappeared)}


def check(df: pd.DataFrame, dataset: str, intervals_per_day: int,
          value_col: str = "SPP") -> QualityReport:
    """Run every check and return a report."""
    report = QualityReport(dataset=dataset, rows=len(df))
    if df.empty:
        return report
    report.duplicates = find_duplicates(df)
    report.gaps = find_gaps(df, intervals_per_day, value_col)
    report.name_changes = find_name_changes(df)
    if value_col in df.columns:
        report.null_prices = int(df[value_col].isna().sum())
    return report


def validate_hub_reconstruction(node_prices: pd.DataFrame, hub: str,
                                members: list[str], value_col: str = "SPP",
                                tolerance: float = 0.01) -> dict:
    """Compare a hub's published price to the mean of its member nodes.

    ERCOT hubs are averages over defined *bus* sets, and the published bus
    weights are not part of these feeds. This check therefore reports the
    discrepancy; it does NOT assert a match, and a large difference is a
    finding about recoverability, not necessarily an error in the data.
    """
    published = node_prices[node_prices["Location"] == hub]
    member_rows = node_prices[node_prices["Location"].isin(members)]
    if published.empty or member_rows.empty:
        return {"hub": hub, "status": "insufficient_data",
                "n_published": len(published), "n_members": len(member_rows)}

    pub = published.set_index("interval_start_utc")[value_col]
    calc = member_rows.groupby("interval_start_utc")[value_col].mean()
    joined = pd.concat([pub.rename("published"), calc.rename("calculated")],
                       axis=1).dropna()
    if joined.empty:
        return {"hub": hub, "status": "no_overlapping_intervals"}

    diff = joined["published"] - joined["calculated"]
    return {
        "hub": hub,
        "status": "compared",
        "intervals": len(joined),
        "mean_abs_diff": float(diff.abs().mean()),
        "max_abs_diff": float(diff.abs().max()),
        "within_tolerance": bool(diff.abs().max() <= tolerance),
        "note": "Hub weights are not published in these feeds; a nonzero "
                "difference is expected and is reported, not corrected.",
    }


def write_report(report: QualityReport, path=None) -> str:
    """Render a report to markdown and write it under reports/quality/."""
    QUALITY_REPORTS.mkdir(parents=True, exist_ok=True)
    path = path or QUALITY_REPORTS / f"{report.dataset}.md"

    lines = [
        f"# Data quality: {report.dataset}",
        "",
        f"- Rows examined: **{report.rows:,}**",
        f"- Duplicate (location, interval) keys: **{len(report.duplicates):,}**",
        f"- Location-days with missing or extra intervals: **{len(report.gaps):,}**",
        f"- Null prices: **{report.null_prices:,}**",
        f"- Settlement points appearing mid-period: "
        f"**{len(report.name_changes.get('appeared', []))}**",
        f"- Settlement points disappearing mid-period: "
        f"**{len(report.name_changes.get('disappeared', []))}**",
        "",
        "> Gaps are reported, never filled. Analyses exclude affected "
        "location-days rather than interpolating them.",
        "",
    ]
    if not report.gaps.empty:
        lines += ["## Worst gaps", "",
                  report.gaps.nlargest(20, "missing").to_markdown(index=False), ""]
    if report.name_changes.get("appeared") or report.name_changes.get("disappeared"):
        lines += ["## Settlement point membership changes", ""]
        for key in ("appeared", "disappeared"):
            names = report.name_changes.get(key, [])
            if names:
                lines.append(f"**{key.title()} ({len(names)}):** "
                             + ", ".join(names[:40])
                             + (" ..." if len(names) > 40 else ""))
                lines.append("")

    text = "\n".join(lines)
    path.write_text(text)
    return text
