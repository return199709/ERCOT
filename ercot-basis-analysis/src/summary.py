"""Print a compact digest of every derived table.

The analysis writes 15 Parquet tables; this renders the handful of numbers a
findings write-up actually rests on, with the sample size beside each so a
figure resting on thin data is visible rather than quoted as fact.

Usage:
    uv run python -m src.summary
"""

from __future__ import annotations

import pandas as pd

from src import db
from src.config import WORST_NODES_TOP_N

pd.set_option("display.width", 150)
pd.set_option("display.max_columns", 40)


def _load(table: str) -> pd.DataFrame | None:
    try:
        return db.read_processed(table)
    except FileNotFoundError:
        return None


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def show(df: pd.DataFrame | None, table: str, columns: list[str] | None = None,
         rows: int = 10) -> None:
    if df is None or df.empty:
        print(f"  ({table} is empty or absent)")
        return
    view = df[columns] if columns else df
    print(view.head(rows).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


def main() -> int:
    section("SCOPE")
    basis = _load("basis")
    if basis is not None and not basis.empty:
        start = pd.to_datetime(basis["interval_start_utc"]).min()
        end = pd.to_datetime(basis["interval_start_utc"]).max()
        print(f"  period            {start:%Y-%m-%d} to {end:%Y-%m-%d}")
        print(f"  node-intervals    {len(basis):,}")
        print(f"  nodes with basis  {basis['basis'].notna().groupby(basis['Location']).any().sum():,}")
        print(f"  hubs referenced   {sorted(basis['assigned_hub'].dropna().unique())}")

    section(f"1. WORST {WORST_NODES_TOP_N} NODES BY MEAN BASIS ($/MWh)")
    show(_load("worst_nodes"), "worst_nodes",
         ["Location", "n", "mean", "p5", "p95", "std"], WORST_NODES_TOP_N)

    section("1b. BEST NODES (premium to hub)")
    by_node = _load("basis_by_node")
    if by_node is not None and not by_node.empty:
        show(by_node.nlargest(10, "mean"), "basis_by_node",
             ["Location", "n", "mean", "p5", "p95"])
        print(f"\n  system-wide mean basis: ${by_node['mean'].mean():,.2f}")
        print(f"  median node basis:      ${by_node['mean'].median():,.2f}")
        print(f"  nodes with negative mean basis: "
              f"{int((by_node['mean'] < 0).sum()):,} of {len(by_node):,} "
              f"({(by_node['mean'] < 0).mean():.1%})")

    section("2. ON-PEAK VERSUS OFF-PEAK (worst nodes)")
    peak = _load("basis_by_node_peak")
    worst = _load("worst_nodes")
    if peak is not None and worst is not None and not worst.empty:
        focus = worst["Location"].head(8)
        show(peak[peak["Location"].isin(focus)].sort_values(["Location", "period"]),
             "basis_by_node_peak", ["Location", "period", "n", "mean", "p5", "p95"], 16)

    section("3. RENEWABLE CORRELATION (most negative)")
    show(_load("renewable_correlations"), "renewable_correlations",
         ["Location", "series", "correlation", "n"], 12)

    section("4. NEGATIVE PRICE INCIDENCE")
    neg = _load("negative_prices_by_node")
    if neg is not None and not neg.empty:
        total_neg = int(neg["negative_intervals"].sum())
        total = int(neg["intervals"].sum())
        print(f"  system: {total_neg:,} of {total:,} intervals negative "
              f"({total_neg / total:.2%})")
        print(f"  settlement points with any negative price: "
              f"{int((neg['negative_intervals'] > 0).sum()):,} of {len(neg):,}\n")
        show(neg, "negative_prices_by_node",
             ["Location", "intervals", "negative_intervals", "negative_share",
              "min_price"], 10)

    section("5. TOP CONSTRAINTS BY CONGESTION COST ($-hours)")
    show(_load("top_constraints"), "top_constraints",
         ["constraint", "total_cost", "intervals_bound", "mean_shadow_price",
          "max_shadow_price"], 15)

    section("6. DA-RT SPREAD -- PERSISTENT BIAS")
    da_rt = _load("da_rt_by_node")
    if da_rt is not None and not da_rt.empty:
        biased = da_rt[da_rt["persistent_bias"].fillna(False)]
        print(f"  flagged persistently biased: {len(biased):,} of {len(da_rt):,}")
        if not biased.empty:
            print(f"  direction split: "
                  f"{biased['bias_direction'].value_counts().to_dict()}\n")
        show(da_rt, "da_rt_by_node",
             ["Location", "n", "mean_spread", "std_spread", "t_stat",
              "bias_direction"], 10)

    section("7. STORAGE SCREEN -- BEST DAILY TOP4-BOTTOM4 SPREAD ($/MWh)")
    show(_load("storage_spread"), "storage_spread",
         ["Location", "days", "mean_spread", "median_spread", "p95_spread"], 12)

    section("DATA QUALITY")
    from src.config import QUALITY_REPORTS
    for path in sorted(QUALITY_REPORTS.glob("*.md")):
        head = [l for l in path.read_text().splitlines() if l.startswith("- ")]
        print(f"\n  {path.name}")
        for line in head:
            print(f"    {line}")

    print("\nEvery figure above comes from ingested ERCOT data. "
          "Sample sizes are in the `n` / `days` / `intervals` columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
