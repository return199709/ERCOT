"""Tests for the data quality checks (synthetic data)."""

import pandas as pd

from src.config import ERCOT_TZ
from src.transform.quality import (
    check, find_duplicates, find_gaps, find_name_changes,
    validate_hub_reconstruction,
)


class TestDuplicates:
    def test_clean_data_reports_none(self, synthetic_dam_prices):
        assert find_duplicates(synthetic_dam_prices).empty

    def test_duplicate_key_is_caught(self, synthetic_dam_prices):
        doubled = pd.concat([synthetic_dam_prices, synthetic_dam_prices.head(1)])
        dupes = find_duplicates(doubled)
        assert len(dupes) == 1
        assert dupes["n"].iloc[0] == 2


class TestGaps:
    def test_complete_day_has_no_gaps(self, synthetic_dam_prices):
        assert find_gaps(synthetic_dam_prices, 24).empty

    def test_missing_hour_is_reported(self, synthetic_dam_prices):
        trimmed = synthetic_dam_prices[
            ~((synthetic_dam_prices["Location"] == "HB_WEST")
              & (synthetic_dam_prices["interval_start_utc"]
                 == synthetic_dam_prices["interval_start_utc"].iloc[0]))
        ]
        gaps = find_gaps(trimmed, 24)
        assert len(gaps) == 1
        assert gaps["missing"].iloc[0] == 1
        assert gaps["Location"].iloc[0] == "HB_WEST"

    def test_gaps_are_not_filled(self, synthetic_dam_prices):
        """find_gaps must never mutate or extend the input."""
        before = len(synthetic_dam_prices)
        find_gaps(synthetic_dam_prices, 24)
        assert len(synthetic_dam_prices) == before


class TestNameChanges:
    def test_detects_appearing_and_disappearing_points(self):
        df = pd.DataFrame({
            "month": ["2025-01", "2025-01", "2025-02", "2025-02"],
            "Location": ["A", "B", "A", "C"],
        })
        changes = find_name_changes(df)
        assert changes["appeared"] == ["C"]
        assert changes["disappeared"] == ["B"]

    def test_single_month_reports_nothing(self):
        df = pd.DataFrame({"month": ["2025-01"], "Location": ["A"]})
        assert find_name_changes(df) == {"appeared": [], "disappeared": []}


class TestHubReconstruction:
    def test_reports_difference_rather_than_asserting_match(self, synthetic_dam_prices):
        result = validate_hub_reconstruction(
            synthetic_dam_prices, "HB_WEST", ["SYNTH_NODE_W"]
        )
        assert result["status"] == "compared"
        # HB_WEST = base-5, node = base-15 -> published is 10 above the "calc"
        assert result["mean_abs_diff"] == 10.0
        assert result["within_tolerance"] is False

    def test_missing_members_reported_not_crashed(self, synthetic_dam_prices):
        result = validate_hub_reconstruction(synthetic_dam_prices, "HB_WEST", ["NOPE"])
        assert result["status"] == "insufficient_data"


class TestCheckReport:
    def test_clean_dataset_is_clean(self, synthetic_dam_prices):
        report = check(synthetic_dam_prices, "synthetic_dam", 24)
        assert report.clean
        assert report.rows == len(synthetic_dam_prices)

    def test_nulls_are_counted(self, synthetic_dam_prices):
        dirty = synthetic_dam_prices.copy()
        dirty.loc[0, "SPP"] = None
        report = check(dirty, "synthetic_dam", 24)
        assert report.null_prices == 1
        assert not report.clean
