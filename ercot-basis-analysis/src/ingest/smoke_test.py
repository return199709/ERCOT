"""Smoke test: confirm ERCOT API credentials work end to end.

Pulls one day of day-ahead market settlement point prices, filters to the
West hub, and prints the row count plus the first five rows.

Usage:
    uv run python src/ingest/smoke_test.py [YYYY-MM-DD]

Defaults to three days ago, which is comfortably past DAM publication.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv
from gridstatus.ercot_api.ercot_api import ErcotAPI

SETTLEMENT_POINT = "HB_WEST"
DEFAULT_LAG_DAYS = 3

# Names only -- values are never read into the output.
REQUIRED_VARS = (
    "ERCOT_API_USERNAME",
    "ERCOT_API_PASSWORD",
    "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY",
)


def check_credentials() -> None:
    """Fail early if .env is missing or incomplete. Never prints values."""
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        sys.exit(
            "Missing credentials: "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill it in."
        )


def target_date() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return (date.today() - timedelta(days=DEFAULT_LAG_DAYS)).isoformat()


def main() -> None:
    load_dotenv()
    check_credentials()

    day = target_date()
    print(f"Pulling DAM settlement point prices for {day}...")

    ercot = ErcotAPI()
    df = ercot.get_spp_day_ahead_hourly(date=day, verbose=True)

    hub = df[df["Location"] == SETTLEMENT_POINT]

    print(f"\nAll settlement points: {len(df):,} rows")
    print(f"{SETTLEMENT_POINT}: {len(hub):,} rows")

    if hub.empty:
        available = sorted(df["Location"].unique())[:10]
        sys.exit(
            f"\nNo rows for {SETTLEMENT_POINT}. "
            f"First locations returned: {available}"
        )

    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(f"\nFirst 5 rows:\n{hub.head(5)}")


if __name__ == "__main__":
    main()
