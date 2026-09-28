"""Registry of ERCOT datasets this project ingests.

Every method name here was verified against the installed gridstatus 0.36.0
by introspection, not taken from documentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    name: str          # partition folder name
    client: str        # "api" (credentialed) or "public" (MIS reports)
    method: str        # method to call on that client
    description: str
    intervals_per_day: int | None = None  # None = irregular / event-driven
    once: bool = False  # point-in-time reference table, not a daily series


DATASETS: dict[str, Dataset] = {
    "dam_spp": Dataset(
        name="dam_spp",
        client="api",
        method="get_spp_day_ahead_hourly",
        description="Day-Ahead Market hourly settlement point prices",
        intervals_per_day=24,
    ),
    "rtm_spp": Dataset(
        name="rtm_spp",
        client="api",
        method="get_spp_real_time_15_min",
        description="Real-Time Market 15-minute settlement point prices",
        intervals_per_day=96,
    ),
    "dam_shadow_prices": Dataset(
        name="dam_shadow_prices",
        client="api",
        method="get_shadow_prices_dam",
        description="DAM binding constraints with shadow prices",
    ),
    "sced_shadow_prices": Dataset(
        name="sced_shadow_prices",
        client="api",
        method="get_shadow_prices_sced",
        description="SCED (real-time) binding constraints with shadow prices",
    ),
    "wind_by_region": Dataset(
        name="wind_by_region",
        client="api",
        method="get_wind_actual_and_forecast_by_geographical_region_hourly",
        description="Hourly wind actuals and forecast by geographic region",
        intervals_per_day=24,
    ),
    "solar_by_region": Dataset(
        name="solar_by_region",
        client="api",
        method="get_solar_actual_and_forecast_by_geographical_region_hourly",
        description="Hourly solar actuals and forecast by geographic region",
        intervals_per_day=24,
    ),
    # Point-in-time reference table, not a daily series: fetched once and
    # reused across the whole period. Kept out of ALL_DATASETS so a monthly
    # ingest doesn't re-download it for every day.
    "settlement_point_mapping": Dataset(
        name="settlement_point_mapping",
        client="public",
        method="get_settlement_points_electrical_bus_mapping",
        description="Settlement point to electrical bus / load zone mapping",
        once=True,
    ),
    "system_load": Dataset(
        name="system_load",
        client="public",
        method="get_system_wide_actual_load",
        description="15-minute system-wide actual load",
        intervals_per_day=96,
    ),
}

# The minimum set needed for the basis calculation itself.
PRICE_DATASETS = ["dam_spp", "rtm_spp"]
CONSTRAINT_DATASETS = ["dam_shadow_prices", "sced_shadow_prices"]
CONTEXT_DATASETS = ["wind_by_region", "solar_by_region", "system_load"]
MAPPING_DATASET = "settlement_point_mapping"

# Daily series only. The mapping is fetched separately via `make ingest-mapping`
# because it is a reference table with no per-day dimension.
ALL_DATASETS = PRICE_DATASETS + CONSTRAINT_DATASETS + CONTEXT_DATASETS


def get(name: str) -> Dataset:
    if name not in DATASETS:
        raise KeyError(
            f"Unknown dataset {name!r}. Known: {sorted(DATASETS)}"
        )
    return DATASETS[name]
