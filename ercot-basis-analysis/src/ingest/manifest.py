"""Append-only ledger that makes ingest idempotent and resumable.

One JSON object per completed (dataset, date) pull. A pull is only recorded
after its Parquet file is written, so an interrupted run never leaves a date
marked complete without data behind it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_RAW

MANIFEST_PATH = DATA_RAW / "_manifest.jsonl"


def _read_all() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    records = []
    with MANIFEST_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # A torn final line from a killed process: ignore it so
                    # the run can resume rather than crash.
                    continue
    return records


def completed_keys() -> set[tuple[str, str]]:
    """Return the set of (dataset, date) pairs already ingested."""
    return {
        (r["dataset"], r["date"])
        for r in _read_all()
        if r.get("status") == "ok"
    }


def is_complete(dataset: str, date: str) -> bool:
    return (dataset, date) in completed_keys()


def record(dataset: str, date: str, rows: int, path: Path, status: str = "ok") -> None:
    """Append one completed pull to the ledger."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset": dataset,
        "date": date,
        "rows": rows,
        "path": str(path.relative_to(DATA_RAW)) if path.is_absolute() else str(path),
        "status": status,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with MANIFEST_PATH.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def summary() -> dict[str, int]:
    """Row counts per dataset, for quick reconciliation."""
    totals: dict[str, int] = {}
    for r in _read_all():
        if r.get("status") == "ok":
            totals[r["dataset"]] = totals.get(r["dataset"], 0) + r.get("rows", 0)
    return totals
