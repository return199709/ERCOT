"""Tests for the seven analysis modules (synthetic data only)."""

import pandas as pd
import pytest

from src.analysis import (
    basis_stats, constraints, da_rt, negative_prices, renewables, storage, trend,
)
from src.analysis.common import resolve_column


class TestCommon:
    def test_resolve_picks_first_available(self):
        df = pd.DataFrame({"b": [1]})
        assert resolve_column(df, ["a", "b"], "thing") == "b"

    def test_resolve_raises_with_available_columns_listed(self):
        with pytest.raises(KeyError, match="available columns"):
            resolve_column(pd.DataFrame({"x": [1]}), ["a"], "thing")


class TestBasisStats:
    def test_by_node_mean_matches_construction(self, synthetic_basis):
        stats = basis_stats.by_node(synthetic_basis).set_index("Location")
        assert stats.loc["SYNTH_NODE_W", "mean"] == -10.0
        assert stats.loc["SYNTH_NODE_N", "mean"] == 2.0

    def test_worst_nodes_ranks_most_negative_first(self, synthetic_basis):
        worst = basis_stats.worst_nodes(synthetic_basis, n=2)
        assert worst["Location"].iloc[0] == "SYNTH_NODE_W"

    def test_peak_split_covers_both_periods(self, synthetic_basis):
        out = basis_stats.by_node_peak(synthetic_basis)
        assert set(out["period"]) == {"on_peak", "off_peak"}

    def test_heatmap_is_hour_by_month(self, synthetic_basis):
        grid = basis_stats.hour_month_heatmap(synthetic_basis, "SYNTH_NODE_W")
        assert grid.index.name == "hour"
        assert (grid.values == -10.0).all()

    def test_percentiles_present(self, synthetic_basis):
        stats = basis_stats.by_node(synthetic_basis)
        assert {"p5", "p95"}.issubset(stats.columns)


class TestNegativePrices:
    def test_counts_negative_intervals(self):
        df = pd.DataFrame({"Location": ["A"] * 4, "SPP": [-1.0, -2.0, 5.0, 10.0]})
        out = negative_prices.by_node(df).set_index("Location")
        assert out.loc["A", "negative_intervals"] == 2
        assert out.loc["A", "negative_share"] == 0.5

    def test_no_negatives_reports_zero(self, synthetic_dam_prices):
        out = negative_prices.by_node(synthetic_dam_prices)
        assert (out["negative_intervals"] == 0).all()

    def test_system_summary_on_empty(self):
        assert negative_prices.system_summary(
            pd.DataFrame({"SPP": []})
        )["intervals"] == 0


class TestStorage:
    def test_spread_is_top4_minus_bottom4(self):
        # 24 hours ramping 0..23: top4 mean 21.5, bottom4 mean 1.5 -> 20
        df = pd.DataFrame({
            "Location": ["A"] * 24,
            "local_date": [pd.Timestamp("2025-06-11").date()] * 24,
            "SPP": list(range(24)),
        })
        out = storage.by_node(df)
        assert out["mean_spread"].iloc[0] == 20.0

    def test_too_few_hours_yields_nan_not_a_bogus_spread(self):
        df = pd.DataFrame({
            "Location": ["A"] * 5,
            "local_date": [pd.Timestamp("2025-06-11").date()] * 5,
            "SPP": [1.0, 2.0, 3.0, 4.0, 5.0],
        })
        assert storage.daily_spread(df)["spread"].isna().all()


class TestConstraints:
    def test_dam_cost_is_shadow_price_times_one_hour(self, synthetic_shadow_prices_dam):
        norm = constraints.normalise(synthetic_shadow_prices_dam, "dam")
        valley = norm[norm["constraint"] == "VALLEY_TIE"]
        assert valley["cost"].sum() == 150.0  # (100 + 50) * 1h

    def test_zero_shadow_price_rows_are_not_counted_as_bound(
            self, synthetic_shadow_prices_dam):
        norm = constraints.normalise(synthetic_shadow_prices_dam, "dam")
        assert "NOT_BOUND" not in set(norm["constraint"])

    def test_sced_intervals_are_weighted_as_five_minutes(
            self, synthetic_shadow_prices_sced):
        norm = constraints.normalise(synthetic_shadow_prices_sced, "sced")
        # 12 intervals x 60 $/MWh x (5/60) h = 60 $-hours
        assert norm["cost"].sum() == pytest.approx(60.0)

    def test_combined_ranking_normalises_across_markets(
            self, synthetic_shadow_prices_dam, synthetic_shadow_prices_sced):
        ranked, _ = constraints.combined(
            synthetic_shadow_prices_dam, synthetic_shadow_prices_sced
        )
        top = ranked.set_index("constraint")
        # VALLEY_TIE: 150 (DAM) + 60 (SCED) = 210
        assert top.loc["VALLEY_TIE", "total_cost"] == pytest.approx(210.0)
        assert ranked["constraint"].iloc[0] == "VALLEY_TIE"

    def test_unknown_columns_raise_clearly(self):
        with pytest.raises(KeyError, match="constraint name"):
            constraints.normalise(pd.DataFrame({"nope": [1]}), "dam")

    def test_empty_input_is_safe(self):
        assert constraints.normalise(pd.DataFrame(), "dam").empty

    def test_seasonality_groups_by_month(self, synthetic_shadow_prices_dam):
        norm = constraints.normalise(synthetic_shadow_prices_dam, "dam")
        out = constraints.seasonality(norm)
        assert set(out["month"]) == {"2025-06"}


class TestDaRt:
    def test_mean_spread_and_bias_flag(self, synthetic_dam_prices, synthetic_rtm_prices):
        from src.transform.basis import da_rt_spread
        spread = da_rt_spread(synthetic_dam_prices, synthetic_rtm_prices)
        out = da_rt.by_node(spread).set_index("Location")
        assert out.loc["SYNTH_NODE_W", "mean_spread"] == 3.0
        # Constant +3 spread has zero variance -> t is undefined, not "biased"
        assert not bool(out.loc["SYNTH_NODE_W", "persistent_bias"])

    def test_noisy_positive_bias_is_flagged(self):
        import numpy as np
        rng = np.random.default_rng(0)
        vals = rng.normal(5.0, 1.0, 200)
        df = pd.DataFrame({"Location": ["A"] * 200, "da_rt_spread": vals})
        out = da_rt.by_node(df).set_index("Location")
        assert bool(out.loc["A", "persistent_bias"])
        assert out.loc["A", "bias_direction"] == "DA_over_RT"


class TestTrend:
    def _two_years(self, y1_basis, y2_basis):
        rows = []
        for year, value in ((2024, y1_basis), (2025, y2_basis)):
            rows += [{"Location": "A", "year": year, "basis": value}] * 50
        return pd.DataFrame(rows)

    def test_yoy_change_computed(self):
        out = trend.yoy_by_node(self._two_years(-5.0, -9.0))
        assert out["yoy_change"].dropna().iloc[0] == -4.0

    def test_widening_negative_is_flagged(self):
        flagged = trend.widening_negative(self._two_years(-5.0, -9.0))
        assert flagged["Location"].tolist() == ["A"]

    def test_improving_basis_not_flagged(self):
        assert trend.widening_negative(self._two_years(-9.0, -5.0)).empty

    def test_single_year_excluded_rather_than_called_unchanged(self):
        df = pd.DataFrame([{"Location": "A", "year": 2025, "basis": -9.0}] * 10)
        assert trend.widening_negative(df).empty


class TestRenewables:
    """Fixtures mirror the REAL ERCOT layout, confirmed against the live feed.

    Both feeds are wide: a `GEN <REGION>` column per region, plus
    `COP HSL <REGION>` capacity columns that must never be read as output.
    Wind and solar use different geographies.
    """

    WIND_COLUMNS = ["GEN COASTAL", "GEN NORTH", "GEN PANHANDLE", "GEN SOUTH",
                    "GEN WEST", "GEN SYSTEM WIDE"]
    SOLAR_COLUMNS = ["GEN CenterEast", "GEN CenterWest", "GEN FarEast",
                     "GEN FarWest", "GEN NorthWest", "GEN SouthEast",
                     "GEN SYSTEM WIDE"]

    def _wind(self, periods=4, freq="15min"):
        idx = pd.date_range("2025-06-11", periods=periods, freq=freq, tz="UTC")
        df = pd.DataFrame({"Interval Start": idx})
        for i, col in enumerate(self.WIND_COLUMNS):
            df[col] = [100.0 * (i + 1) + j * 100 for j in range(periods)]
        # Capacity columns that must be ignored.
        for col in self.WIND_COLUMNS:
            df[col.replace("GEN ", "COP HSL ")] = 9999.0
        return df

    def test_finds_only_generation_columns_not_capacity(self):
        found = renewables.generation_columns(self._wind())
        assert set(found) == {"COASTAL", "NORTH", "PANHANDLE", "SOUTH",
                              "WEST", "SYSTEM WIDE"}

    def test_capacity_columns_are_never_treated_as_output(self):
        """COP HSL is High Sustained Limit -- capacity, not generation."""
        out = renewables.prepare_generation(self._wind(), "wind")
        assert not any("9999" in str(v) for v in out.values.ravel())
        assert not any("hsl" in c.lower() for c in out.columns)

    def test_averages_subhourly_rows_to_the_hour(self):
        out = renewables.prepare_generation(self._wind(), "wind", ["WEST"])
        assert len(out) == 1
        # GEN WEST is the 5th column: 500,600,700,800 -> mean 650
        assert out["wind_west_mw"].iloc[0] == 650.0

    def test_region_names_normalised(self):
        out = renewables.prepare_generation(self._wind(), "wind", ["SYSTEM WIDE"])
        assert "wind_system_wide_mw" in out.columns

    def test_solar_uses_its_own_geography(self):
        idx = pd.date_range("2025-06-11", periods=2, freq="h", tz="UTC")
        df = pd.DataFrame({"Interval Start": idx})
        for col in self.SOLAR_COLUMNS:
            df[col] = 50.0
        found = renewables.generation_columns(df)
        assert "FarWest" in found
        # The live solar feed has no Panhandle or West at all.
        assert "PANHANDLE" not in found and "WEST" not in found

    def test_requesting_a_wind_region_from_solar_raises(self):
        """Wind and solar geographies differ; a silent drop would hide a series."""
        idx = pd.date_range("2025-06-11", periods=2, freq="h", tz="UTC")
        df = pd.DataFrame({"Interval Start": idx})
        for col in self.SOLAR_COLUMNS:
            df[col] = 50.0
        with pytest.raises(KeyError, match="different"):
            renewables.prepare_generation(df, "solar", ["PANHANDLE"])

    def test_no_generation_columns_raises_rather_than_substituting(self):
        df = pd.DataFrame({"Interval Start": [pd.Timestamp("2025-06-11", tz="UTC")],
                           "COP HSL WEST": [100.0]})
        with pytest.raises(KeyError, match="capacity"):
            renewables.prepare_generation(df, "wind")

    def test_empty_frame_is_safe(self):
        assert renewables.prepare_generation(pd.DataFrame(), "wind").empty

    def test_correlation_requires_enough_pairs(self, synthetic_basis):
        gen = pd.DataFrame({
            "hour_start_utc": pd.to_datetime(
                synthetic_basis["interval_start_utc"]).dt.floor("h").unique(),
        })
        gen["wind_west_mw"] = range(len(gen))
        joined = renewables.join_basis_to_generation(synthetic_basis, gen)
        # 24 hourly pairs per node is below the 30-pair floor -> not reported
        assert renewables.correlations(joined).empty

    def test_no_generation_columns_returns_empty_correlations(self, synthetic_basis):
        assert renewables.correlations(synthetic_basis).empty
