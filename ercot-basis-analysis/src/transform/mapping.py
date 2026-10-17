"""Settlement point classification and hub assignment.

ERCOT publishes no node->hub mapping. Trading hubs are averages over defined
sets of electrical buses, so assigning a resource node to a hub is an analyst
decision, not a lookup. This project uses the node's load zone as the proxy
(LZ_WEST -> HB_WEST, and so on), which is recorded in ASSUMPTIONS.md.

Nodes whose load zone cannot be determined are NEVER guessed. They are
returned in an `unmapped` list so the caller can report them and exclude them,
rather than silently attributing them to the wrong hub.

Two sources are allowed, both lookups rather than inferences: the settlement
point list (`build_zone_map`), and inheritance from a listed node whose price
series is identical over the whole period, which means the same electrical bus
(`extend_zone_map_by_shared_series`).
"""

from __future__ import annotations

import pandas as pd

from src.config import (
    HUB_PREFIX,
    LOAD_ZONE_PREFIX,
    REFERENCE_HUBS,
    TRADING_HUBS,
    ZONE_TO_HUB,
)

HUB = "hub"
LOAD_ZONE = "load_zone"
RESOURCE_NODE = "resource_node"


def classify_location(name: str) -> str:
    """Classify a settlement point by its ERCOT name prefix."""
    if not isinstance(name, str):
        return RESOURCE_NODE
    upper = name.upper()
    if upper.startswith(HUB_PREFIX):
        return HUB
    if upper.startswith(LOAD_ZONE_PREFIX):
        return LOAD_ZONE
    return RESOURCE_NODE


def add_location_type(df: pd.DataFrame, col: str = "Location") -> pd.DataFrame:
    out = df.copy()
    out["location_class"] = out[col].map(classify_location)
    return out


def build_zone_map(mapping_df: pd.DataFrame) -> dict[str, str]:
    """Build settlement point -> load zone from ERCOT's settlement point list.

    The settlement point list is the only authoritative source for which zone
    a resource node sits in. Column naming varies between report revisions, so
    candidates are probed and a clear error is raised if none match -- better
    than silently producing an empty map.
    """
    # "Resource Node" is the live column name, confirmed against the real
    # settlement point list. The earlier uppercase guesses are kept for
    # older report revisions.
    sp_candidates = ["Resource Node", "SETTLEMENT_POINT", "Settlement Point",
                     "SettlementPoint", "RESOURCE_NODE",
                     "Settlement Point Name", "Node Name"]
    zone_candidates = ["Settlement Load Zone", "SETTLEMENT_LOAD_ZONE",
                       "LOAD_ZONE", "Load Zone", "Zone"]

    sp_col = next((c for c in sp_candidates if c in mapping_df.columns), None)
    zone_col = next((c for c in zone_candidates if c in mapping_df.columns), None)

    if sp_col is None or zone_col is None:
        raise KeyError(
            "Could not find settlement point / load zone columns in the "
            f"mapping table. Available columns: {list(mapping_df.columns)}. "
            "Update the candidate lists in build_zone_map rather than "
            "guessing an assignment."
        )

    pairs = mapping_df[[sp_col, zone_col]].dropna().drop_duplicates()
    return dict(zip(pairs[sp_col].astype(str), pairs[zone_col].astype(str)))


def extend_zone_map_by_shared_series(
    zone_map: dict[str, str],
    prices: pd.DataFrame,
    value_col: str = "SPP",
) -> tuple[dict[str, str], pd.DataFrame]:
    """Give unmapped settlement points the zone of a point they price with.

    ERCOT's settlement point list names each resource node once, but the DAM
    price feed carries extra names for the same electrical bus: unit-level
    names such as `FOO_CC1` and `FOO_CC2` beside the `FOO_RN` the list knows.
    Those extra names settle at the bus LMP, so their price series is
    byte-identical to the listed node's, hour for hour.

    This is a lookup, not a guess: an identical price series over the whole
    period means the same bus, and the same bus is in exactly one load zone.
    The rule is deliberately strict:

    * a point is recovered only if every *mapped* member of its group sits in
      one zone; a group whose mapped members disagree recovers nothing;
    * a group with no mapped member recovers nothing;
    * points already in `zone_map` are never changed.

    Returns the extended map and a provenance table with one row per
    recovered point: which node it inherited from, the zone, how many
    intervals the two series agree on, and groups that were skipped and why.
    """
    # Imported here: quality -> time_utils -> config; no cycle, but keep the
    # mapping module importable without pulling the quality stack.
    from src.transform.quality import find_identical_series

    columns = ["Location", "zone", "inherited_from", "intervals", "status"]
    extended = dict(zone_map)
    rows: list[dict] = []

    groups = find_identical_series(prices, value_col)
    if groups.empty:
        return extended, pd.DataFrame(columns=columns)

    for _, group in groups.iterrows():
        members = [m.strip() for m in str(group["locations"]).split(",")]
        nodes = [m for m in members if classify_location(m) == RESOURCE_NODE]
        mapped = {m: zone_map[m] for m in nodes if m in zone_map}
        unmapped = [m for m in nodes if m not in zone_map]
        if not unmapped:
            continue
        zones = set(mapped.values())
        if not mapped:
            status, zone, source = "skipped_no_mapped_member", None, None
        elif len(zones) > 1:
            status, zone, source = "skipped_zone_conflict", None, None
        else:
            status, zone = "recovered", zones.pop()
            source = sorted(mapped)[0]
        for name in unmapped:
            if status == "recovered":
                extended[name] = zone
            rows.append({
                "Location": name,
                "zone": zone,
                "inherited_from": source,
                "intervals": int(group["intervals"]),
                "status": status,
            })

    return extended, pd.DataFrame(rows, columns=columns)


def assign_hub(
    locations: pd.Series,
    zone_map: dict[str, str] | None = None,
) -> tuple[pd.Series, list[str]]:
    """Assign each settlement point its reference hub.

    Returns (assigned_hub, unmapped_names). Hubs map to themselves; load zones
    map via ZONE_TO_HUB; resource nodes map via their zone. Anything that
    cannot be resolved becomes NA and is listed in `unmapped`.
    """
    zone_map = zone_map or {}
    assigned = []
    unmapped: list[str] = []

    for name in locations:
        kind = classify_location(name)
        if kind == HUB:
            assigned.append(name if name in REFERENCE_HUBS else pd.NA)
        elif kind == LOAD_ZONE:
            assigned.append(ZONE_TO_HUB.get(name, pd.NA))
            if name not in ZONE_TO_HUB:
                unmapped.append(name)
        else:
            zone = zone_map.get(name)
            hub = ZONE_TO_HUB.get(zone) if zone else None
            if hub is None:
                assigned.append(pd.NA)
                unmapped.append(name)
            else:
                assigned.append(hub)

    return pd.Series(assigned, index=locations.index, dtype="object"), sorted(set(unmapped))


def hub_frame(prices: pd.DataFrame, value_col: str = "SPP") -> pd.DataFrame:
    """Wide table of hub prices per interval, for joining onto node prices."""
    hubs = prices[prices["Location"].isin(REFERENCE_HUBS)]
    return hubs.pivot_table(
        index="interval_start_utc", columns="Location",
        values=value_col, aggfunc="mean",
    ).reset_index()


def known_hubs_present(prices: pd.DataFrame) -> list[str]:
    """Which of the four trading hubs actually appear in the data."""
    present = set(prices["Location"].unique())
    return [h for h in TRADING_HUBS if h in present]
