"""Central configuration: paths, calendars, and the hub-assignment policy.

Every methodological choice that could reasonably have gone another way is
defined here rather than buried in a module, so ASSUMPTIONS.md can point at
one file.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
REPORTS = PROJECT_ROOT / "reports"
QUALITY_REPORTS = REPORTS / "quality"
DUCKDB_PATH = PROJECT_ROOT / "data" / "ercot.duckdb"

# ERCOT operates on Central Prevailing Time. Every table also carries a UTC
# column so that DST transitions are unambiguous.
ERCOT_TZ = "US/Central"

# --- Settlement point taxonomy -------------------------------------------
# ERCOT settlement point names are prefixed by type. Anything that is not a
# hub or a load zone is treated as a resource node.
HUB_PREFIX = "HB_"
LOAD_ZONE_PREFIX = "LZ_"

TRADING_HUBS = ["HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_HOUSTON"]
# Bus-average hub, used as a secondary ERCOT-wide reference.
HUB_BUSAVG = "HB_BUSAVG"
REFERENCE_HUBS = TRADING_HUBS + [HUB_BUSAVG]

# --- Hub assignment policy -----------------------------------------------
# ERCOT publishes no node->hub mapping: hubs are averages over defined bus
# sets. We therefore assign each node the hub of its load zone. The four
# NOIE zones have no hub of their own and are mapped geographically; these
# four are judgment calls and are recorded in ASSUMPTIONS.md.
ZONE_TO_HUB = {
    "LZ_NORTH": "HB_NORTH",
    "LZ_SOUTH": "HB_SOUTH",
    "LZ_WEST": "HB_WEST",
    "LZ_HOUSTON": "HB_HOUSTON",
    "LZ_AEN": "HB_SOUTH",      # Austin Energy
    "LZ_CPS": "HB_SOUTH",      # CPS Energy (San Antonio)
    "LZ_LCRA": "HB_SOUTH",     # Lower Colorado River Authority
    "LZ_RAYBN": "HB_NORTH",    # Rayburn Country EC
}

# --- Peak definition ------------------------------------------------------
# ERCOT 5x16: hours ending 07:00-22:00 CPT, Monday-Friday, excluding NERC
# holidays. Everything else is off-peak.
PEAK_START_HOUR = 7
PEAK_END_HOUR = 22
PEAK_WEEKDAYS = (0, 1, 2, 3, 4)  # Monday=0

# NERC holidays observed by ERCOT for on/off-peak classification.
NERC_HOLIDAYS = [
    "New Year's Day", "Memorial Day", "Independence Day",
    "Labor Day", "Thanksgiving Day", "Christmas Day",
]

# --- Interval expectations (used by the quality checks) -------------------
DAM_INTERVALS_PER_DAY = 24        # hourly
RTM_INTERVALS_PER_DAY = 96        # 15-minute

# --- Battery dispatch model ----------------------------------------------
# A 100 MWh / 4-hour lithium-ion system, the shape most built in ERCOT.
# Degradation is priced per MWh of throughput rather than capped as a cycle
# count, because that is what actually restrains cycling economically.
BATTERY_POWER_MW = 25.0
BATTERY_DURATION_HOURS = 4.0
BATTERY_ROUND_TRIP_EFFICIENCY = 0.85
BATTERY_DEGRADATION_COST_PER_MWH = 5.0

# --- Analysis parameters --------------------------------------------------
WORST_NODES_TOP_N = 25
TOP_CONSTRAINTS_N = 15
STORAGE_TOP_HOURS = 4             # top-4 minus bottom-4 hour spread
BASIS_PERCENTILES = (0.05, 0.95)  # P5 / P95

# --- Renewable region taxonomies ------------------------------------------
# The wind and solar feeds are WIDE: one `GEN <REGION>` column per region,
# alongside `COP HSL <REGION>` capacity columns that are NOT actuals.
#
# The two feeds use entirely different geographies, confirmed against the live
# feeds. They therefore cannot be compared region-for-region, and there is no
# solar "Panhandle" or "West" at all -- the nearest solar analogues to the
# windy west are FarWest and NorthWest.
WIND_REGIONS = ["COASTAL", "NORTH", "PANHANDLE", "SOUTH", "WEST", "SYSTEM WIDE"]
SOLAR_REGIONS = ["CenterEast", "CenterWest", "FarEast", "FarWest",
                 "NorthWest", "SouthEast", "SYSTEM WIDE"]

# Focus regions for the basis-versus-renewables analysis.
WIND_FOCUS_REGIONS = ["WEST", "PANHANDLE"]
SOLAR_FOCUS_REGIONS = ["FarWest", "NorthWest"]

# Prefix identifying actual generation columns in both feeds.
GENERATION_PREFIX = "GEN "


def ensure_dirs() -> None:
    """Create the data and report directories if they do not exist."""
    for path in (DATA_RAW, DATA_PROCESSED, REPORTS, QUALITY_REPORTS):
        path.mkdir(parents=True, exist_ok=True)
