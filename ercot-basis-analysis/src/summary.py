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
        with_basis = basis["basis"].notna().groupby(basis["Location"]).any().sum()
        print(f"  nodes with basis  {with_basis:,}")
        print(f"  hubs referenced   {sorted(basis['assigned_hub'].dropna().unique())}")

    section("SHARED PRICE SERIES (read before any ranking)")
    raw = None
    try:
        raw = db.read_raw("dam_spp")
    except FileNotFoundError:
        pass
    if raw is not None and not raw.empty:
        from src.transform.quality import find_identical_series
        from src.transform.time_utils import ensure_utc
        shared = find_identical_series(ensure_utc(raw, "Interval Start"))
        if shared.empty:
            print("  Every settlement point has a distinct price series.")
        else:
            covered = int(shared["n_locations"].sum())
            print(f"  {len(shared):,} groups of settlement points share an "
                  f"identical price series, covering {covered:,} locations.")
            print("  They resolve to the same electrical bus. Real market "
                  "behaviour, but they are NOT independent observations:")
            print("  a top-25 list may cover far fewer distinct series.\n")
            print(shared.head(12).to_string(index=False))

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
    top = _load("top_constraints")
    cols = ["constraint", "total_cost", "intervals_bound", "mean_shadow_price",
            "max_shadow_price"]
    if top is not None and "element" in top.columns:
        cols.insert(1, "element")
    show(top, "top_constraints", cols, 15)

    section("5b. WHICH CONSTRAINT DRIVES EACH NODE (DAM basis ~ DAM shadow prices)")
    attr = _load("attribution_by_node")
    if attr is not None and not attr.empty:
        print(f"  nodes fitted: {len(attr):,} on "
              f"{int(attr['n_constraints'].iloc[0])} constraints")
        print(f"  R²: median {attr['r2'].median():.2f}, "
              f"{int((attr['r2'] >= 0.5).sum()):,} nodes >= 0.5, "
              f"{int((attr['r2'] < 0).sum()):,} nodes < 0 (constraints outside "
              f"the top set, or none)")
        print("\n  worst nodes and the constraint behind them:")
        node_cols = ["Location", "mean_basis", "residual_mean", "r2",
                     "dominant_constraint", "dominant_contribution", "dominant_share"]
        if "dominant_element" in attr.columns:
            node_cols.insert(5, "dominant_element")
        show(attr, "attribution_by_node", node_cols, 15)
        print("\n  constraints by how many nodes they dominate:")
        by_c = _load("attribution_by_constraint")
        c_cols = ["constraint", "nodes_dominated", "nodes_affected",
                  "total_abs_contribution", "mean_shadow_price_all_hours",
                  "hours_bound"]
        if by_c is not None and "element" in by_c.columns:
            c_cols.insert(1, "element")
        show(by_c, "attribution_by_constraint", c_cols, 12)
        print("  nodes_dominated and nodes_affected apply the materiality floors "
              "in config ($/MWh of mean basis).")
    else:
        print("  (attribution_by_node is empty or absent)")

    section("6. DA-RT SPREAD -- PERSISTENT BIAS")
    da_rt = _load("da_rt_by_node")
    if da_rt is not None and not da_rt.empty:
        biased = da_rt[da_rt["persistent_bias"].fillna(False)]
        print(f"  flagged persistently biased: {len(biased):,} of {len(da_rt):,}")
        if not biased.empty:
            print(f"  direction split: "
                  f"{biased['bias_direction'].value_counts().to_dict()}\n")
        strongest = biased.reindex(biased["t_stat"].abs()
                                   .sort_values(ascending=False).index)
        print("  strongest flagged biases (by |t|):")
        show(strongest, "da_rt_by_node",
             ["Location", "n", "mean_spread", "std_spread", "t_stat",
              "bias_direction"], 10)

    section("7. STORAGE SCREEN -- BEST DAILY TOP4-BOTTOM4 SPREAD ($/MWh)")
    show(_load("storage_spread"), "storage_spread",
         ["Location", "days", "mean_spread", "median_spread", "p95_spread"], 12)

    section("7b. OPTIMAL BATTERY DISPATCH ($/kW-year, 100 MWh / 4h)")
    print("  Solved subject to round-trip efficiency, power rating, state of")
    print("  charge and degradation, with perfect foresight. Perfect foresight")
    print("  makes this the MAXIMUM EXTRACTABLE value, not a trading backtest.\n")
    show(_load("dispatch_by_node"), "dispatch_by_node",
         ["Location", "days", "revenue_per_day", "annual_per_kw", "mean_cycles"], 12)

    section("7c. WHERE THAT REVENUE COMES FROM")
    split = _load("dispatch_decomposition")
    if split is not None and not split.empty:
        print("  hub_revenue is what a battery at the trading hubs would have")
        print("  earned from the system-wide price shape. basis_revenue is the")
        print("  part attributable to this node's own congestion.\n")
        show(split, "dispatch_decomposition",
             ["Location", "node_revenue", "hub_revenue", "basis_revenue",
              "basis_share"], 12)
        print(f"\n  median basis share: {split['basis_share'].median():.1%}")
        print(f"  nodes where basis ADDS value: "
              f"{int((split['basis_revenue'] > 0).sum()):,} of {len(split):,}")

    section("DATA QUALITY")
    from src.config import QUALITY_REPORTS
    for path in sorted(QUALITY_REPORTS.glob("*.md")):
        head = [line for line in path.read_text().splitlines() if line.startswith("- ")]
        print(f"\n  {path.name}")
        for line in head:
            print(f"    {line}")

    print("\nEvery figure above comes from ingested ERCOT data. "
          "Sample sizes are in the `n` / `days` / `intervals` columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
