"""Tests for settlement point classification and hub assignment (synthetic)."""

import pandas as pd

from src.transform.mapping import (
    DC_TIE,
    HUB,
    LOAD_ZONE,
    RESOURCE_NODE,
    assign_hub,
    build_zone_map,
    classify_location,
)


class TestClassify:
    def test_hub_prefix(self):
        assert classify_location("HB_WEST") == HUB

    def test_load_zone_prefix(self):
        assert classify_location("LZ_NORTH") == LOAD_ZONE

    def test_anything_else_is_a_node(self):
        assert classify_location("SYNTH_NODE_W") == RESOURCE_NODE

    def test_non_string_is_a_node(self):
        assert classify_location(None) == RESOURCE_NODE

    def test_dc_tie_prefix(self):
        assert classify_location("DC_E") == DC_TIE


class TestAssignHub:
    def test_node_takes_its_zones_hub(self, zone_map):
        hubs, unmapped = assign_hub(pd.Series(["SYNTH_NODE_W"]), zone_map)
        assert hubs.iloc[0] == "HB_WEST"
        assert unmapped == []

    def test_load_zone_maps_to_its_hub(self):
        hubs, _ = assign_hub(pd.Series(["LZ_HOUSTON"]), {})
        assert hubs.iloc[0] == "HB_HOUSTON"

    def test_hub_maps_to_itself(self):
        hubs, _ = assign_hub(pd.Series(["HB_SOUTH"]), {})
        assert hubs.iloc[0] == "HB_SOUTH"

    def test_unknown_node_is_reported_not_guessed(self):
        """The critical safety property: never invent an assignment."""
        hubs, unmapped = assign_hub(pd.Series(["MYSTERY_NODE"]), {})
        assert pd.isna(hubs.iloc[0])
        assert unmapped == ["MYSTERY_NODE"]

    def test_dc_tie_is_excluded_but_not_reported_unmapped(self):
        """A DC tie has no zone to look up; it is not a mapping failure."""
        hubs, unmapped = assign_hub(pd.Series(["DC_E", "MYSTERY_NODE"]), {})
        assert pd.isna(hubs.iloc[0])
        assert unmapped == ["MYSTERY_NODE"]

    def test_noie_zone_maps_geographically(self):
        hubs, _ = assign_hub(pd.Series(["LZ_CPS"]), {})
        assert hubs.iloc[0] == "HB_SOUTH"


class TestBuildZoneMap:
    def test_reads_recognised_columns(self):
        df = pd.DataFrame({"SETTLEMENT_POINT": ["N1"], "SETTLEMENT_LOAD_ZONE": ["LZ_WEST"]})
        assert build_zone_map(df) == {"N1": "LZ_WEST"}

    def test_unrecognised_columns_raise_rather_than_return_empty(self):
        import pytest
        with pytest.raises(KeyError, match="Could not find"):
            build_zone_map(pd.DataFrame({"foo": [1], "bar": [2]}))
