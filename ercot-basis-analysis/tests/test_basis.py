"""Tests for basis and DA-RT spread maths (synthetic data)."""

import pandas as pd

from src.transform.basis import compute_basis, da_rt_spread, rtm_to_hourly


class TestComputeBasis:
    def test_basis_is_node_minus_assigned_hub(self, synthetic_dam_prices, zone_map):
        out, unmapped = compute_basis(synthetic_dam_prices, zone_map)
        assert unmapped == []
        west = out[out["Location"] == "SYNTH_NODE_W"]
        # node = base-15, HB_WEST = base-5  ->  basis = -10 everywhere
        assert (west["basis"] == -10.0).all()

    def test_positive_basis_node(self, synthetic_dam_prices, zone_map):
        out, _ = compute_basis(synthetic_dam_prices, zone_map)
        north = out[out["Location"] == "SYNTH_NODE_N"]
        assert (north["basis"] == 2.0).all()

    def test_hubs_and_zones_excluded_from_node_table(self, synthetic_dam_prices, zone_map):
        out, _ = compute_basis(synthetic_dam_prices, zone_map)
        assert not out["Location"].str.startswith(("HB_", "LZ_")).any()

    def test_basis_against_every_reference_hub_is_present(self, synthetic_dam_prices, zone_map):
        out, _ = compute_basis(synthetic_dam_prices, zone_map)
        assert "basis_vs_HB_WEST" in out.columns
        assert "basis_vs_HB_NORTH" in out.columns
        west = out[out["Location"] == "SYNTH_NODE_W"]
        # vs HB_NORTH (= base): base-15 - base = -15
        assert (west["basis_vs_HB_NORTH"] == -15.0).all()

    def test_unmapped_node_yields_na_basis_not_a_guess(self, synthetic_dam_prices):
        """Without a zone map the node must not be silently assigned a hub."""
        out, unmapped = compute_basis(synthetic_dam_prices, zone_map={})
        assert "SYNTH_NODE_W" in unmapped
        assert out["basis"].isna().all()

    def test_missing_columns_raise(self):
        import pytest
        with pytest.raises(KeyError):
            compute_basis(pd.DataFrame({"Location": ["X"]}))


class TestRtmToHourly:
    def test_four_intervals_collapse_to_one_hour(self, synthetic_rtm_prices):
        hourly = rtm_to_hourly(synthetic_rtm_prices)
        assert (hourly["rt_intervals"] == 4).all()
        assert len(hourly) == 24 * 2  # 2 locations x 24 hours


class TestDaRtSpread:
    def test_spread_is_da_minus_rt(self, synthetic_dam_prices, synthetic_rtm_prices):
        spread = da_rt_spread(synthetic_dam_prices, synthetic_rtm_prices)
        west = spread[spread["Location"] == "SYNTH_NODE_W"]
        # DA = base-15, RT = base-18 -> +3
        assert (west["da_rt_spread"] == 3.0).all()

    def test_only_overlapping_locations_survive_the_join(self, synthetic_dam_prices,
                                                         synthetic_rtm_prices):
        spread = da_rt_spread(synthetic_dam_prices, synthetic_rtm_prices)
        assert set(spread["Location"]) == {"HB_WEST", "SYNTH_NODE_W"}
