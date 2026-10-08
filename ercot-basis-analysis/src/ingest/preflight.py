"""Preflight check: validate every assumption before a long backfill.

Pulls ONE day of each dataset and reports what actually came back, so a
column-name mismatch surfaces in a few minutes rather than several hours into
a 24-month backfill.

Checks, in order:
  1. Credentials present (names only, never values)
  2. Each ERCOT host reachable
  3. One day of each dataset fetches, with row counts
  4. The column names this project depends on are present

Exit code 0 means the pipeline's assumptions hold and a backfill is safe to
start. Non-zero names what to fix.

Usage:
    uv run python -m src.ingest.preflight [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from datetime import date as date_cls
from datetime import timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

from src.analysis import constraints as constraints_mod
from src.analysis import renewables as renewables_mod
from src.config import SOLAR_FOCUS_REGIONS, WIND_FOCUS_REGIONS
from src.ingest import datasets as ds
from src.ingest.client import (
    MissingCredentialsError, REQUIRED_VARS, get_ercot, get_ercot_api,
)

ERCOT_HOSTS = ("api.ercot.com", "ercotb2c.b2clogin.com", "www.ercot.com")

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


def _mark(status: str) -> str:
    return {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", SKIP: " skip "}[status]


# Column contracts: (dataset, concept, candidate names, required?)
# Each entry mirrors a candidate list used in the transform/analysis code, so a
# mismatch here is exactly the mismatch that would break that module.
COLUMN_CONTRACTS: list[tuple[str, str, list[str], bool]] = [
    ("dam_spp", "settlement point", ["Location"], True),
    ("dam_spp", "price", ["SPP"], True),
    ("dam_spp", "interval start", ["Interval Start"], True),
    ("rtm_spp", "settlement point", ["Location"], True),
    ("rtm_spp", "price", ["SPP"], True),
    ("rtm_spp", "interval start", ["Interval Start"], True),
    ("dam_shadow_prices", "constraint name",
     constraints_mod.CONSTRAINT_NAME_CANDIDATES, True),
    ("dam_shadow_prices", "shadow price",
     constraints_mod.SHADOW_PRICE_CANDIDATES, True),
    ("dam_shadow_prices", "timestamp", constraints_mod.TIME_CANDIDATES, True),
    ("sced_shadow_prices", "constraint name",
     constraints_mod.CONSTRAINT_NAME_CANDIDATES, True),
    ("sced_shadow_prices", "shadow price",
     constraints_mod.SHADOW_PRICE_CANDIDATES, True),
    ("sced_shadow_prices", "timestamp", constraints_mod.TIME_CANDIDATES, True),
    ("system_load", "interval start", ["Interval Start"], False),
]

# Settlement point -> load zone, the mapping basis depends on entirely.
MAPPING_CONTRACTS = [
    ("settlement point", ["Resource Node", "SETTLEMENT_POINT", "Settlement Point",
                          "SettlementPoint", "RESOURCE_NODE",
                          "Settlement Point Name", "Node Name"]),
    ("load zone", ["Settlement Load Zone", "SETTLEMENT_LOAD_ZONE", "LOAD_ZONE",
                   "Load Zone", "Zone"]),
]


def check_credentials() -> tuple[str, str]:
    """Report which required variables are set. Never prints a value.

    Loads .env first: the variables normally live there rather than in the
    ambient environment, and checking before loading reports every credential
    as missing on a correctly configured machine.
    """
    load_dotenv()
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        return FAIL, ("missing or empty: " + ", ".join(missing)
                      + " -- copy .env.example to .env and fill it in")
    return PASS, f"all {len(REQUIRED_VARS)} required variables set"


def check_host(host: str, timeout: float = 8.0) -> tuple[str, str]:
    """Check the host over HTTPS, via the same path gridstatus uses.

    Deliberately uses `requests` rather than a raw socket. A raw socket
    bypasses HTTPS_PROXY, so in any proxied environment it reports success
    while every real API call fails at the proxy -- precisely the false
    reassurance this preflight exists to prevent.

    Any HTTP status counts as reachable: a 403 or 404 from the origin still
    proves the request got there.
    """
    try:
        socket.gethostbyname(host)
    except socket.gaierror as exc:
        return FAIL, f"DNS lookup failed ({exc})"

    try:
        response = requests.get(f"https://{host}/", timeout=timeout)
        return PASS, f"reachable over HTTPS (HTTP {response.status_code})"
    except requests.exceptions.ProxyError as exc:
        return FAIL, (f"blocked by an HTTP proxy ({str(exc)[:100]}). This "
                      "machine's egress policy is denying ERCOT; no credential "
                      "can fix it. Run from a network that allows ERCOT")
    except requests.exceptions.SSLError as exc:
        return FAIL, f"TLS verification failed ({str(exc)[:100]})"
    except requests.exceptions.RequestException as exc:
        return FAIL, f"cannot reach ({type(exc).__name__}: {str(exc)[:100]})"


def validate_columns(dataset: str, df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Check this dataset's column contracts against what actually arrived."""
    results = []
    for name, concept, candidates, required in COLUMN_CONTRACTS:
        if name != dataset:
            continue
        found = next((c for c in candidates if c in df.columns), None)
        if found:
            results.append((PASS, concept, f"using {found!r}"))
        else:
            results.append((
                FAIL if required else WARN,
                concept,
                f"none of {candidates} present. Actual columns: "
                f"{sorted(df.columns)[:12]}",
            ))
    return results


# The wide renewable feeds need a structural check, not a name lookup.
RENEWABLE_REGIONS = {
    "wind_by_region": ("wind", WIND_FOCUS_REGIONS),
    "solar_by_region": ("solar", SOLAR_FOCUS_REGIONS),
}


def validate_renewable(dataset: str, df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Check the wide `GEN <REGION>` layout and that focus regions exist."""
    fuel, focus = RENEWABLE_REGIONS[dataset]
    found = renewables_mod.generation_columns(df)
    if not found:
        return [(FAIL, "generation columns",
                 f"no '{renewables_mod.GENERATION_PREFIX}<REGION>' columns. "
                 f"Actual: {sorted(df.columns)[:12]}")]

    results = [(PASS, "generation columns",
                f"{len(found)} regions: {sorted(found)}")]
    missing = [r for r in focus if r not in found]
    if missing:
        results.append((FAIL, "focus regions",
                        f"{missing} absent. Present: {sorted(found)}. "
                        "Update the region list in src/config.py"))
    else:
        results.append((PASS, "focus regions", f"{focus} all present"))
    return results


def probe_dataset(name: str, day: date_cls, verbose: bool) -> tuple[str, str, list]:
    """Fetch one day and validate its columns."""
    spec = ds.get(name)
    try:
        client = get_ercot_api() if spec.client == "api" else get_ercot()
        df = getattr(client, spec.method)(date=day.isoformat(), verbose=verbose)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the whole check
        return FAIL, f"fetch failed: {type(exc).__name__}: {str(exc)[:160]}", []

    if df is None or df.empty:
        return WARN, f"fetched but returned no rows for {day}", []

    detail = f"{len(df):,} rows, {len(df.columns)} columns"
    if spec.intervals_per_day and "Location" in df.columns:
        locations = df["Location"].nunique()
        expected = locations * spec.intervals_per_day
        detail += (f", {locations:,} locations "
                   f"({len(df):,} vs {expected:,} expected)")
    if name in RENEWABLE_REGIONS:
        return PASS, detail, validate_renewable(name, df)
    return PASS, detail, validate_columns(name, df)


def probe_mapping(day: date_cls, verbose: bool) -> tuple[str, str, list]:
    try:
        df = get_ercot().get_settlement_points_electrical_bus_mapping(
            date=day.isoformat(), verbose=verbose
        )
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"fetch failed: {type(exc).__name__}: {str(exc)[:160]}", []
    if df is None or df.empty:
        return FAIL, "returned no rows -- nodes cannot be assigned to hubs", []

    results = []
    for concept, candidates in MAPPING_CONTRACTS:
        found = next((c for c in candidates if c in df.columns), None)
        results.append(
            (PASS, concept, f"using {found!r}") if found
            else (FAIL, concept,
                  f"none of {candidates} present. Actual: {sorted(df.columns)[:12]}")
        )
    return PASS, f"{len(df):,} rows, {len(df.columns)} columns", results


def run(day: date_cls, verbose: bool = False) -> int:
    failures = 0
    warnings = 0

    def report(status, label, detail, indent=0):
        nonlocal failures, warnings
        if status == FAIL:
            failures += 1
        elif status == WARN:
            warnings += 1
        print(f"{'  ' * indent}[{_mark(status)}] {label}: {detail}")

    print(f"ERCOT pipeline preflight -- probing {day}\n")

    print("1. Credentials")
    cred_status, cred_detail = check_credentials()
    report(cred_status, "environment", cred_detail, 1)
    if cred_status == FAIL:
        print("\nStopping: cannot probe the API without credentials.")
        return 1

    print("\n2. Network reachability")
    for host in ERCOT_HOSTS:
        status, detail = check_host(host)
        report(status, host, detail, indent=1)
    if failures:
        print("\nStopping: ERCOT is not reachable from this machine, so no "
              "dataset can be probed. Nothing is wrong with the pipeline.")
        return 2

    print("\n3. Settlement point -> load zone mapping (basis depends on this)")
    status, detail, cols = probe_mapping(day, verbose)
    report(status, "settlement_point_mapping", detail, 1)
    for s, concept, d in cols:
        report(s, concept, d, 2)

    print("\n4. Datasets")
    for name in ds.ALL_DATASETS:
        status, detail, cols = probe_dataset(name, day, verbose)
        report(status, name, detail, 1)
        for s, concept, d in cols:
            report(s, concept, d, 2)

    print(f"\n{'-' * 64}")
    if failures:
        print(f"{failures} failure(s), {warnings} warning(s).")
        print("Fix the failures above before starting a backfill. A column "
              "mismatch means updating the candidate list in the module named "
              "for that concept -- do not guess a mapping.")
        return 1
    print(f"All checks passed ({warnings} warning(s)). Safe to run: "
          f"make ingest MONTH={day.strftime('%Y-%m')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pipeline assumptions.")
    parser.add_argument("--date", help="YYYY-MM-DD to probe (default: 3 days ago)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    day = (pd.Timestamp(args.date).date() if args.date
           else date_cls.today() - timedelta(days=3))
    try:
        return run(day, args.verbose)
    except MissingCredentialsError as exc:
        print(f"CREDENTIALS: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
