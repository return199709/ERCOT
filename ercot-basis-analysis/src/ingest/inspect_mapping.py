"""Inspect the settlement point list to settle two open questions with data.

1. Which column actually holds the settlement point name that appears as
   `Location` in the SPP feeds? Measured by set overlap, not assumed.

2. Is the `Hub` column a usable node-to-hub relationship? If ERCOT publishes
   one, it replaces this project's largest assumption -- that a node can be
   referenced to the hub of its load zone (ASSUMPTIONS.md section 1).

Reports measurements only. It changes no code and writes no data, so a
surprising answer is a decision for a human, not something to auto-apply.

Usage:
    uv run python -m src.ingest.inspect_mapping [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from datetime import date as date_cls
from datetime import timedelta

import pandas as pd

from src.config import ZONE_TO_HUB
from src.ingest.client import get_ercot, get_ercot_api
from src.transform.mapping import RESOURCE_NODE, classify_location

SP_CANDIDATES = ["Resource Node", "Node Name", "Electrical Bus", "Hub Bus Name",
                 "Substation", "PSSE Bus Name"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the SP mapping table.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: 10 days ago)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    day = (pd.Timestamp(args.date).date() if args.date
           else date_cls.today() - timedelta(days=10))

    print(f"Inspecting the settlement point list as of {day}\n")

    mapping = get_ercot().get_settlement_points_electrical_bus_mapping(
        date=day.isoformat(), verbose=args.verbose
    )
    print(f"Mapping table: {len(mapping):,} rows, {len(mapping.columns)} columns")
    print(f"Columns: {sorted(mapping.columns)}\n")

    prices = get_ercot_api().get_spp_day_ahead_hourly(
        date=day.isoformat(), verbose=args.verbose
    )
    locations = set(prices["Location"].unique())
    nodes = {loc for loc in locations if classify_location(loc) == RESOURCE_NODE}
    print(f"DAM SPP: {len(locations):,} settlement points, "
          f"{len(nodes):,} of them resource nodes\n")

    # --- Question 1: which column names the settlement point? -------------
    print("1. Which mapping column matches the SPP `Location` values?")
    print(f"   {'column':<18} {'distinct':>9} {'matched':>9} {'coverage':>9}")
    best, best_cover = None, 0.0
    for col in SP_CANDIDATES:
        if col not in mapping.columns:
            continue
        values = set(mapping[col].dropna().astype(str).str.strip())
        matched = values & nodes
        coverage = len(matched) / len(nodes) if nodes else 0.0
        print(f"   {col:<18} {len(values):>9,} {len(matched):>9,} "
              f"{coverage:>8.1%}")
        if coverage > best_cover:
            best, best_cover = col, coverage
    if best is None:
        print("   No candidate column found. The report layout has changed.")
        return 1
    print(f"\n   -> best: {best!r} covering {best_cover:.1%} of resource nodes")
    if best_cover < 0.5:
        print("   WARNING: under half the nodes matched. Do not rely on this "
              "mapping until the gap is understood.")

    # --- Question 2: is `Hub` a usable node->hub relationship? ------------
    print("\n2. Is the `Hub` column a published node-to-hub mapping?")
    if "Hub" not in mapping.columns:
        print("   No `Hub` column. The load-zone proxy stands.")
    else:
        hub = mapping["Hub"]
        non_null = int(hub.notna().sum())
        print(f"   populated: {non_null:,} of {len(mapping):,} rows "
              f"({non_null / len(mapping):.1%})")
        values = sorted(hub.dropna().astype(str).str.strip().unique())
        print(f"   distinct values ({len(values)}): {values[:12]}")

        pairs = mapping[[best, "Hub"]].dropna()
        pairs = pairs[pairs[best].astype(str).str.strip().isin(nodes)]
        nodes_with_hub = pairs[best].astype(str).str.strip().nunique()
        print(f"   resource nodes carrying a hub: {nodes_with_hub:,} "
              f"of {len(nodes):,} ({nodes_with_hub / len(nodes):.1%})")

    # --- How far does the current load-zone proxy actually get? -----------
    print("\n3. Coverage of the load-zone proxy currently in use")
    zone_col = next((c for c in ("Settlement Load Zone", "SETTLEMENT_LOAD_ZONE")
                     if c in mapping.columns), None)
    if zone_col is None:
        print("   No load zone column found.")
    else:
        zoned = mapping[[best, zone_col]].dropna()
        zoned = zoned[zoned[best].astype(str).str.strip().isin(nodes)]
        zones = set(zoned[zone_col].astype(str).str.strip())
        mapped_nodes = zoned[
            zoned[zone_col].astype(str).str.strip().isin(ZONE_TO_HUB)
        ][best].astype(str).str.strip().nunique()
        print(f"   zones present: {sorted(zones)}")
        unknown = sorted(zones - set(ZONE_TO_HUB))
        if unknown:
            print(f"   zones NOT in ZONE_TO_HUB (would be unmapped): {unknown}")
        print(f"   nodes the proxy can assign: {mapped_nodes:,} of "
              f"{len(nodes):,} ({mapped_nodes / len(nodes):.1%})")

    print("\nNothing was written. Decide based on the numbers above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
