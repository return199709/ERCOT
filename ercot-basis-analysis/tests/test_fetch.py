"""Tests for ingest orchestration (stubbed clients; no network)."""

from datetime import date

import pandas as pd
import pytest

from src.ingest import datasets as ds
from src.ingest import fetch

PROBE_DAY = date(2025, 6, 1)


class TestDatasetRegistry:
    def test_mapping_dataset_resolves_by_name(self):
        """Regression: `make ingest-mapping` raised KeyError here."""
        spec = ds.get("settlement_point_mapping")
        assert spec.once is True

    def test_mapping_excluded_from_the_daily_sweep(self):
        """A reference table must not be pulled once per day by `make ingest`."""
        assert ds.MAPPING_DATASET not in ds.ALL_DATASETS

    def test_daily_datasets_are_not_marked_once(self):
        assert all(not ds.get(n).once for n in ds.ALL_DATASETS)

    def test_unknown_name_lists_the_known_ones(self):
        with pytest.raises(KeyError, match="Known:"):
            ds.get("nope")


class _StubClient:
    """Records how the fetch method was called."""

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_settlement_points_electrical_bus_mapping(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


@pytest.fixture
def stub_mapping(monkeypatch, tmp_path):
    frame = pd.DataFrame({
        "SETTLEMENT_POINT": ["N1", "N2"],
        "SETTLEMENT_LOAD_ZONE": ["LZ_WEST", "LZ_NORTH"],
    })
    client = _StubClient(frame)
    monkeypatch.setattr(fetch, "get_ercot", lambda: client)
    monkeypatch.setattr(fetch, "DATA_RAW", tmp_path)
    monkeypatch.setattr(fetch.manifest, "record", lambda *a, **k: None)
    return client, tmp_path


class TestFetchOnce:
    def test_fetches_exactly_once_over_a_month(self, stub_mapping):
        """The bug behind the bug: a 30-day range must not mean 30 downloads."""
        client, _ = stub_mapping
        start, end = fetch.month_bounds("2025-06")
        assert (end - start).days == 29  # a real 30-day span
        fetch.fetch_range("settlement_point_mapping", start, end)
        assert len(client.calls) == 1

    def test_passes_the_required_date(self, stub_mapping):
        """gridstatus raises "Must supply either 'date' or 'start'" without it.

        The signature defaults date to None, but @support_date_range enforces
        it anyway -- a real run failed here before this was fixed.
        """
        client, _ = stub_mapping
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        assert client.calls[0]["date"] == "2025-06-01"

    def test_writes_a_flat_unpartitioned_file(self, stub_mapping):
        _, root = stub_mapping
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        written = list(root.rglob("*.parquet"))
        assert len(written) == 1
        assert written[0].name == "settlement_point_mapping.parquet"
        assert "year=" not in str(written[0])

    def test_second_run_is_idempotent(self, stub_mapping):
        client, _ = stub_mapping
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        assert len(client.calls) == 1  # second run skipped

    def test_force_refetches(self, stub_mapping):
        client, _ = stub_mapping
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY, force=True)
        assert len(client.calls) == 2

    def test_empty_response_raises_rather_than_writing_an_empty_table(
            self, monkeypatch, tmp_path):
        client = _StubClient(pd.DataFrame())
        monkeypatch.setattr(fetch, "get_ercot", lambda: client)
        monkeypatch.setattr(fetch, "DATA_RAW", tmp_path)
        with pytest.raises(RuntimeError, match="without it"):
            fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        assert not list(tmp_path.rglob("*.parquet"))

    def test_written_table_is_readable_by_the_zone_mapper(self, stub_mapping):
        """End to end: what fetch writes must be what mapping.py can consume."""
        from src.transform.mapping import build_zone_map
        _, root = stub_mapping
        fetch.fetch_once("settlement_point_mapping", PROBE_DAY)
        df = pd.read_parquet(root / "settlement_point_mapping"
                             / "settlement_point_mapping.parquet")
        assert build_zone_map(df) == {"N1": "LZ_WEST", "N2": "LZ_NORTH"}


class TestMonthBounds:
    def test_covers_the_whole_month(self):
        start, end = fetch.month_bounds("2025-02")
        assert str(start) == "2025-02-01" and str(end) == "2025-02-28"
