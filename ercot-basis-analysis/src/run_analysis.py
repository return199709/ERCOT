"""Run the full analysis pipeline over whatever has been ingested.

Reads raw Parquet, applies quality checks, computes basis, runs the seven
analyses, and writes derived tables to data/processed plus quality reports to
reports/quality.

Nothing here invents data. If an input is missing the step is skipped and
reported; if a required input is missing the run fails with an explanation.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from src import db
from src.analysis import (
    basis_stats, constraints, da_rt, negative_prices, renewables, storage, trend,
)
from src.config import SOLAR_FOCUS_REGIONS, WIND_FOCUS_REGIONS, ensure_dirs
from src.transform import quality
from src.transform.basis import compute_basis, da_rt_spread
from src.transform.mapping import build_zone_map
from src.transform.time_utils import add_time_parts, ensure_utc


def _load(dataset: str) -> pd.DataFrame | None:
    try:
        return db.read_raw(dataset)
    except FileNotFoundError as exc:
        print(f"  skip {dataset}: {exc}", file=sys.stderr)
        return None


def _prepare_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Attach UTC and calendar columns to a settlement point price table."""
    time_col = "Interval Start" if "Interval Start" in df.columns else None
    if time_col is None:
        raise KeyError(
            f"price table has no 'Interval Start' column; got {list(df.columns)}"
        )
    out = ensure_utc(df, time_col)
    return add_time_parts(out, time_col)


def _zone_map() -> dict[str, str]:
    mapping = _load("settlement_point_mapping")
    if mapping is None or mapping.empty:
        print("  WARNING: no settlement point mapping ingested. Resource nodes "
              "cannot be assigned to hubs and basis will be unavailable for "
              "them. Ingest the 'settlement_point_mapping' dataset.",
              file=sys.stderr)
        return {}
    return build_zone_map(mapping)


def run(verbose: bool = False) -> int:
    ensure_dirs()
    written: list[str] = []

    dam = _load("dam_spp")
    if dam is None:
        print("\nFATAL: dam_spp is required for every basis analysis. "
              "Run `make ingest MONTH=YYYY-MM` first.", file=sys.stderr)
        return 1

    dam = _prepare_prices(dam)
    print(f"DAM settlement point prices: {len(dam):,} rows, "
          f"{dam['Location'].nunique():,} locations")

    # --- quality ---------------------------------------------------------
    dam_report = quality.check(dam, "dam_spp", 24)
    quality.write_report(dam_report)
    print(f"  quality: {len(dam_report.gaps)} gap rows, "
          f"{len(dam_report.duplicates)} duplicate keys, "
          f"{dam_report.null_prices} null prices")

    # --- basis -----------------------------------------------------------
    zone_map = _zone_map()
    basis, unmapped = compute_basis(dam, zone_map)
    if unmapped:
        print(f"  WARNING: {len(unmapped)} settlement points could not be "
              f"assigned a hub and are excluded (first 10: {unmapped[:10]})",
              file=sys.stderr)
    basis = add_time_parts(basis, "Interval Start") if "Interval Start" in basis \
        else basis
    written.append(str(db.write_processed(basis, "basis")))

    usable = basis.dropna(subset=["basis"])
    if usable.empty:
        print("\nNo node had a resolvable hub assignment, so no basis "
              "statistics can be produced. This is a mapping problem, not an "
              "empty dataset -- see the warning above.", file=sys.stderr)
        return 1

    # --- analyses 1, 2, 4, 7 (DAM prices) --------------------------------
    written.append(str(db.write_processed(basis_stats.by_node(usable), "basis_by_node")))
    written.append(str(db.write_processed(basis_stats.by_node_peak(usable),
                                          "basis_by_node_peak")))
    written.append(str(db.write_processed(basis_stats.by_month(usable),
                                          "basis_by_month")))
    written.append(str(db.write_processed(basis_stats.worst_nodes(usable),
                                          "worst_nodes")))
    written.append(str(db.write_processed(trend.yoy_by_node(usable), "basis_yoy")))
    written.append(str(db.write_processed(trend.widening_negative(usable),
                                          "widening_negative")))
    written.append(str(db.write_processed(negative_prices.by_node(dam),
                                          "negative_prices_by_node")))
    written.append(str(db.write_processed(negative_prices.by_node_month(dam),
                                          "negative_prices_by_month")))
    written.append(str(db.write_processed(storage.by_node(dam), "storage_spread")))

    # --- analysis 6 (needs RTM) ------------------------------------------
    rtm = _load("rtm_spp")
    if rtm is not None:
        rtm = _prepare_prices(rtm)
        rtm_report = quality.check(rtm, "rtm_spp", 96)
        quality.write_report(rtm_report)
        spread = da_rt_spread(dam, rtm)
        written.append(str(db.write_processed(spread, "da_rt_spread")))
        written.append(str(db.write_processed(da_rt.by_node(spread), "da_rt_by_node")))
        print(f"  DA-RT spread computed over {len(spread):,} node-hours")
    else:
        print("  RTM prices absent: analysis 6 (DA vs RT) skipped")

    # --- analysis 5 (constraints) ----------------------------------------
    dam_sp = _load("dam_shadow_prices")
    sced_sp = _load("sced_shadow_prices")
    if dam_sp is not None or sced_sp is not None:
        ranked, allrows = constraints.combined(
            dam_sp if dam_sp is not None else pd.DataFrame(),
            sced_sp if sced_sp is not None else pd.DataFrame(),
        )
        written.append(str(db.write_processed(ranked, "top_constraints")))
        if not allrows.empty:
            written.append(str(db.write_processed(constraints.seasonality(allrows),
                                                  "constraint_seasonality")))
        print(f"  constraints ranked: {len(ranked)} rows")
    else:
        print("  shadow prices absent: analysis 5 (constraints) skipped")

    # --- analysis 3 (renewables) -----------------------------------------
    # Both feeds are wide (one GEN <REGION> column per region) and use
    # different geographies, so each is prepared against its own region list.
    wind = _load("wind_by_region")
    solar = _load("solar_by_region")
    gens = []
    for frame, fuel, focus in ((wind, "wind", WIND_FOCUS_REGIONS),
                               (solar, "solar", SOLAR_FOCUS_REGIONS)):
        if frame is None or frame.empty:
            continue
        try:
            prepared = renewables.prepare_generation(frame, fuel, focus)
            if not prepared.empty:
                gens.append(prepared)
                print(f"  {fuel}: {len(prepared):,} hours, "
                      f"{len(prepared.columns) - 1} region series")
        except KeyError as exc:
            print(f"  {fuel} generation unusable: {exc}", file=sys.stderr)

    if gens:
        joined = renewables.join_basis_to_generation(usable, *gens)
        corr = renewables.correlations(joined)
        written.append(str(db.write_processed(corr, "renewable_correlations")))
        print(f"  renewable correlations: {len(corr)} node-series pairs")
    else:
        print("  wind/solar absent: analysis 3 (renewables) skipped")

    views = db.register_views()
    print(f"\nWrote {len(written)} processed tables; "
          f"registered {len(views)} DuckDB views.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ERCOT basis analyses.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    return run(verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
