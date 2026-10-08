"""Day-by-day ERCOT ingest: idempotent, resumable, rate-limit aware.

Design notes
------------
* Idempotent: a (dataset, date) already in the manifest with its Parquet file
  present is skipped. Re-running a completed month pulls nothing.
* Resumable: the manifest is appended after each successful day, so an
  interrupted backfill resumes exactly where it stopped.
* Rate-limit aware: transient failures (429, 5xx, connection resets) get
  exponential backoff. Permanent failures (bad credentials, egress policy
  denials) fail fast -- retrying those is pointless and is explicitly
  discouraged by the environment's proxy guidance.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.config import DATA_RAW, ensure_dirs
from src.ingest import datasets as ds
from src.ingest import manifest
from src.ingest.client import MissingCredentialsError, get_ercot, get_ercot_api

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 2.0

# Substrings that mean "do not retry" -- the request will never succeed.
PERMANENT_ERROR_MARKERS = (
    "403",
    "unauthorized",
    "forbidden",
    "invalid_grant",
    "tunnel connection failed",
    "unable to connect to proxy",
)


class PermanentIngestError(RuntimeError):
    """A failure that retrying cannot fix (auth, or blocked egress)."""


def partition_path(dataset: str, day: date_cls) -> Path:
    """data/raw/<dataset>/year=YYYY/month=MM/<dataset>_YYYY-MM-DD.parquet"""
    return (
        DATA_RAW
        / dataset
        / f"year={day.year}"
        / f"month={day.month:02d}"
        / f"{dataset}_{day.isoformat()}.parquet"
    )


def _is_permanent(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in PERMANENT_ERROR_MARKERS)


def _call_with_backoff(fn, day: date_cls | None, verbose: bool) -> pd.DataFrame:
    """Call a gridstatus fetch method, retrying only transient failures.

    `day` of None omits the date argument entirely, which reference tables
    need: they have no per-day dimension and return the current snapshot.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if day is None:
                return fn(verbose=verbose)
            return fn(date=day.isoformat(), verbose=verbose)
        except Exception as exc:  # noqa: BLE001 - classify then re-raise
            last_exc = exc
            if _is_permanent(exc):
                raise PermanentIngestError(
                    f"Permanent failure fetching {day}: {exc}\n"
                    "This is an authentication or network-policy denial, not a "
                    "transient error. Retrying will not help."
                ) from exc
            if attempt == MAX_ATTEMPTS:
                break
            wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed ({exc}); "
                  f"retrying in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {day} after {MAX_ATTEMPTS} attempts: {last_exc}")


def snapshot_path(dataset: str) -> Path:
    """Flat path for a reference table: no year/month partitioning."""
    return DATA_RAW / dataset / f"{dataset}.parquet"


def fetch_once(dataset_name: str, day: date_cls, force: bool = False,
               verbose: bool = False) -> int:
    """Fetch a point-in-time reference table a single time.

    Reference tables such as the settlement point list have no per-day
    dimension. Looping them over a date range would re-download the same
    table once per day and write dozens of identical partitions.

    A date is still required even though the gridstatus signature defaults it
    to None: the @support_date_range decorator raises
    "Must supply either 'date' or 'start'" when it is omitted. One snapshot is
    taken as of `day` and reused for the whole period.
    """
    spec = ds.get(dataset_name)
    out_path = snapshot_path(dataset_name)

    if not force and out_path.exists():
        print(f"  {dataset_name}: already present, skipping "
              f"(use --force to refresh)")
        return 0

    client = get_ercot_api() if spec.client == "api" else get_ercot()
    df = _call_with_backoff(getattr(client, spec.method), day, verbose)

    if df is None or df.empty:
        raise RuntimeError(
            f"{dataset_name} returned no rows. Basis cannot be computed "
            "without it, because resource nodes could not be assigned to a "
            "load zone. Not writing an empty table."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    manifest.record(dataset_name, "snapshot", len(df), out_path)
    print(f"  {dataset_name}: {len(df):,} rows, {len(df.columns)} columns "
          f"-> {out_path.relative_to(DATA_RAW.parent)}")
    print(f"    columns: {sorted(df.columns)[:10]}")
    return len(df)


def fetch_day(
    dataset_name: str,
    day: date_cls,
    force: bool = False,
    verbose: bool = False,
) -> int:
    """Fetch one day. Returns the row count (0 if skipped). Idempotent."""
    spec = ds.get(dataset_name)
    out_path = partition_path(dataset_name, day)
    iso = day.isoformat()

    if not force and manifest.is_complete(dataset_name, iso) and out_path.exists():
        return 0

    client = get_ercot_api() if spec.client == "api" else get_ercot()
    method = getattr(client, spec.method)

    df = _call_with_backoff(method, day, verbose)
    if df is None or df.empty:
        # Record the gap explicitly. We never invent rows to fill it.
        manifest.record(dataset_name, iso, 0, out_path, status="empty")
        print(f"  {dataset_name} {iso}: NO DATA RETURNED (recorded as gap)")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    manifest.record(dataset_name, iso, len(df), out_path)
    return len(df)


def daterange(start: date_cls, end: date_cls):
    """Inclusive day iterator."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def fetch_range(
    dataset_name: str,
    start: date_cls,
    end: date_cls,
    force: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    ensure_dirs()

    if ds.get(dataset_name).once:
        n = fetch_once(dataset_name, start, force=force, verbose=verbose)
        return {"days_fetched": 1 if n else 0, "days_skipped": 0 if n else 1,
                "rows": n}

    fetched = skipped = rows = 0
    for day in daterange(start, end):
        n = fetch_day(dataset_name, day, force=force, verbose=verbose)
        if n:
            fetched += 1
            rows += n
            print(f"  {dataset_name} {day}: {n:,} rows")
        else:
            skipped += 1
    return {"days_fetched": fetched, "days_skipped": skipped, "rows": rows}


def month_bounds(month: str) -> tuple[date_cls, date_cls]:
    """'YYYY-MM' -> (first day, last day)."""
    start = pd.Timestamp(f"{month}-01").date()
    end = (pd.Timestamp(start) + pd.offsets.MonthEnd(1)).date()
    return start, end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest ERCOT data.")
    parser.add_argument("--month", help="YYYY-MM (one calendar month)")
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument(
        "--datasets", default=",".join(ds.ALL_DATASETS),
        help="comma-separated dataset names",
    )
    parser.add_argument("--force", action="store_true", help="re-fetch existing days")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.month:
        start, end = month_bounds(args.month)
    elif args.start and args.end:
        start = pd.Timestamp(args.start).date()
        end = pd.Timestamp(args.end).date()
    else:
        parser.error("supply --month, or both --start and --end")

    names = [n.strip() for n in args.datasets.split(",") if n.strip()]
    print(f"Ingesting {len(names)} dataset(s) from {start} to {end}")

    try:
        for name in names:
            print(f"\n=== {name} ===")
            stats = fetch_range(name, start, end, args.force, args.verbose)
            print(f"  -> {stats['days_fetched']} fetched, "
                  f"{stats['days_skipped']} skipped, {stats['rows']:,} rows")
    except MissingCredentialsError as exc:
        print(f"\nCREDENTIALS: {exc}", file=sys.stderr)
        return 2
    except PermanentIngestError as exc:
        print(f"\nSTOPPED: {exc}", file=sys.stderr)
        return 3

    print(f"\nManifest totals: {manifest.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
