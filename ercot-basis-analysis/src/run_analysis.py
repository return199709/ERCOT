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
    attribution,
    basis_stats,
    constraints,
    da_rt,
    dispatch,
    negative_prices,
    renewables,
    storage,
    trend,
)
from src.config import (
    BATTERY_DEGRADATION_COST_PER_MWH,
    BATTERY_DURATION_HOURS,
    BATTERY_POWER_MW,
    BATTERY_ROUND_TRIP_EFFICIENCY,
    SOLAR_FOCUS_REGIONS,
    TRADING_HUBS,
    WIND_FOCUS_REGIONS,
    ensure_dirs,
)
from src.transform import quality
from src.transform.basis import compute_basis, da_rt_spread
from src.transform.mapping import (
    build_zone_map,
    extend_zone_map_by_shared_series,
)
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
    print(f"  quality: {len(dam_report.gaps)} gap location-days "
          f"({dam_report.absent_location_days} wholly absent), "
          f"{len(dam_report.partial_coverage)} locations not spanning the "
          f"period, {len(dam_report.duplicates)} duplicate keys, "
          f"{dam_report.null_prices} null prices")
    if not dam_report.gaps.empty:
        print("  -> reported in reports/quality/dam_spp.md; gaps are never "
              "filled. Statistics carry an `n` column so a thin node is "
              "visible rather than silently equal-weighted.")

    # --- basis -----------------------------------------------------------
    zone_map = _zone_map()
    # Second lookup, not a guess: a point whose price series is identical to
    # a listed node's over the whole period sits on the same bus, and so in
    # the same zone. Conflicting or orphan groups recover nothing.
    zone_map, recovered = extend_zone_map_by_shared_series(zone_map, dam)
    if not recovered.empty:
        written.append(str(db.write_processed(recovered, "zone_map_recovered")))
        counts = recovered["status"].value_counts().to_dict()
        print(f"  zone map: {counts.get('recovered', 0)} settlement points "
              f"inherited a zone from a node sharing their price series; "
              f"skipped {counts.get('skipped_no_mapped_member', 0)} with no "
              f"mapped twin and {counts.get('skipped_zone_conflict', 0)} "
              f"with conflicting zones")
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

    # --- analysis 7b: optimal battery dispatch (energy model) ------------
    # The screen above is a price heuristic. This solves the operating
    # problem subject to efficiency, power, state of charge and degradation.
    spec = dispatch.BatterySpec(
        power_mw=BATTERY_POWER_MW,
        duration_hours=BATTERY_DURATION_HOURS,
        round_trip_efficiency=BATTERY_ROUND_TRIP_EFFICIENCY,
        degradation_cost_per_mwh=BATTERY_DEGRADATION_COST_PER_MWH,
    )
    print(f"  dispatching a {spec.energy_mwh:.0f} MWh / "
          f"{spec.duration_hours:.0f}h battery at every node "
          f"(this is the slow step)...")
    node_daily = dispatch.dispatch_series(
        dam[dam["Location"].isin(usable["Location"].unique())], spec
    )
    if not node_daily.empty:
        written.append(str(db.write_processed(node_daily, "dispatch_daily")))
        ranked = dispatch.annualise(node_daily, spec)
        written.append(str(db.write_processed(ranked, "dispatch_by_node")))
        print(f"  dispatch: {len(node_daily):,} node-days, "
              f"best ${ranked['annual_per_kw'].iloc[0]:,.0f}/kW-yr, "
              f"median ${ranked['annual_per_kw'].median():,.0f}/kW-yr")

        # A battery at the hub earns from the system-wide price shape;
        # anything beyond that is this node's basis.
        hub_daily = dispatch.dispatch_series(
            dam[dam["Location"].isin(TRADING_HUBS)], spec
        )
        if not hub_daily.empty:
            split = dispatch.decompose(node_daily, hub_daily)
            written.append(str(db.write_processed(split, "dispatch_decomposition")))
            print(f"  decomposition: median basis share of dispatch revenue "
                  f"{split['basis_share'].median():.1%}")

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

    # --- analysis 5b: which constraints drive each node's basis ----------
    # Basis is linear in DAM shadow prices with node-minus-hub shift factor
    # differences as coefficients; those are estimated per node by least
    # squares. Same-market fit: DAM basis on DAM shadow prices.
    if dam_sp is not None:
        by_node, contrib, by_constraint = attribution.attribute(usable, dam_sp)
        if by_node.empty:
            print("  attribution: no node had enough overlapping hours with "
                  "the shadow price matrix; skipped", file=sys.stderr)
        else:
            written.append(str(db.write_processed(by_node, "attribution_by_node")))
            written.append(str(db.write_processed(contrib, "attribution_contributions")))
            written.append(str(db.write_processed(by_constraint,
                                                  "attribution_by_constraint")))
            print(f"  attribution: {len(by_node):,} nodes fitted on "
                  f"{int(by_node['n_constraints'].iloc[0])} constraints; "
                  f"median R² {by_node['r2'].median():.2f}; "
                  f"{int((by_node['r2'] >= 0.5).sum()):,} nodes with R² >= 0.5")
    else:
        print("  DAM shadow prices absent: analysis 5b (attribution) skipped")

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
