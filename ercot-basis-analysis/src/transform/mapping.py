"""Settlement point classification and hub assignment.

ERCOT publishes no node->hub mapping. Trading hubs are averages over defined
sets of electrical buses, so assigning a resource node to a hub is an analyst
decision, not a lookup. This project uses the node's load zone as the proxy
(LZ_WEST -> HB_WEST, and so on), which is recorded in ASSUMPTIONS.md.

Nodes whose load zone cannot be determined are NEVER guessed. They are
returned in an `unmapped` list so the caller can report them and exclude them,
rather than silently attributing them to the wrong hub.
"""

from __future__ import annotations

import pandas as pd

from src.config import (
    HUB_PREFIX, LOAD_ZONE_PREFIX, REFERENCE_HUBS, TRADING_HUBS, ZONE_TO_HUB,
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
    sp_candidates = ["SETTLEMENT_POINT", "Settlement Point", "SettlementPoint",
                     "RESOURCE_NODE", "Settlement Point Name"]
    zone_candidates = ["SETTLEMENT_LOAD_ZONE", "Settlement Load Zone",
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
