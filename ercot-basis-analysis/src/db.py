"""DuckDB access over the partitioned Parquet lake.

DuckDB reads Parquet directly, so no load step is needed: views point at the
partition globs and stay correct as new months land.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.config import DATA_PROCESSED, DATA_RAW, DUCKDB_PATH


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DUCKDB_PATH), read_only=read_only)


def _glob(root: Path, dataset: str) -> str:
    return str(root / dataset / "**" / "*.parquet")


def dataset_exists(dataset: str, root: Path = DATA_RAW) -> bool:
    return any((root / dataset).rglob("*.parquet"))


def read_raw(dataset: str) -> pd.DataFrame:
    """Read every partition of a raw dataset into a DataFrame."""
    if not dataset_exists(dataset, DATA_RAW):
        raise FileNotFoundError(
            f"No Parquet files under data/raw/{dataset}. "
            f"Run `make ingest MONTH=YYYY-MM` first."
        )
    with connect(read_only=False) as con:
        return con.execute(
            f"SELECT * FROM read_parquet('{_glob(DATA_RAW, dataset)}')"
        ).df()


def read_processed(table: str) -> pd.DataFrame:
    if not dataset_exists(table, DATA_PROCESSED):
        raise FileNotFoundError(
            f"No Parquet files under data/processed/{table}. Run `make analyze`."
        )
    with connect(read_only=False) as con:
        return con.execute(
            f"SELECT * FROM read_parquet('{_glob(DATA_PROCESSED, table)}')"
        ).df()


def write_processed(df: pd.DataFrame, table: str) -> Path:
    """Write a derived table as a single Parquet file."""
    out_dir = DATA_PROCESSED / table
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{table}.parquet"
    df.to_parquet(path, index=False)
    return path


def register_views() -> list[str]:
    """Create a DuckDB view per available dataset, for ad-hoc SQL."""
    created = []
    with connect() as con:
        for root, prefix in ((DATA_RAW, "raw"), (DATA_PROCESSED, "processed")):
            if not root.exists():
                continue
            for child in sorted(p for p in root.iterdir() if p.is_dir()):
                if not any(child.rglob("*.parquet")):
                    continue
                view = f"{prefix}_{child.name}"
                con.execute(
                    f"CREATE OR REPLACE VIEW {view} AS "
                    f"SELECT * FROM read_parquet('{_glob(root, child.name)}')"
                )
                created.append(view)
    return created
