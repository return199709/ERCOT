"""Tests for the battery dispatch model.

Each case has an optimum derivable by hand, so these check the solver is
correct, not merely that it runs.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.dispatch import (
    BatterySpec,
    annualise,
    decompose,
    dispatch_day,
    dispatch_series,
)

# 100 MWh / 4-hour battery.
LOSSLESS = BatterySpec(power_mw=25.0, duration_hours=4.0,
                       round_trip_efficiency=1.0,
                       degradation_cost_per_mwh=0.0, soc_steps=40)
REALISTIC = BatterySpec(power_mw=25.0, duration_hours=4.0,
                        round_trip_efficiency=0.85,
                        degradation_cost_per_mwh=5.0, soc_steps=40)


def two_price_day(low: float, high: float) -> np.ndarray:
    """4 cheap hours, then 4 expensive, padded to 24 with a mid price."""
    prices = np.full(24, (low + high) / 2)
    prices[0:4] = low
    prices[4:8] = high
    return prices


class TestKnownOptima:
    def test_flat_prices_yield_no_revenue(self):
        """No spread, nothing to arbitrage. Idling must beat cycling."""
        result = dispatch_day(np.full(24, 50.0), LOSSLESS)
        assert result["revenue"] == pytest.approx(0.0, abs=1e-6)
        assert result["throughput_mwh"] == pytest.approx(0.0)

    def test_lossless_arbitrage_equals_capacity_times_spread(self):
        """Buy 100 MWh at 10, sell at 100 -> 100 x 90 = $9,000."""
        result = dispatch_day(two_price_day(10.0, 100.0), LOSSLESS)
        assert result["revenue"] == pytest.approx(9000.0, rel=1e-6)

    def test_efficiency_loss_is_priced_on_the_charge_side(self):
        """Buying 100/0.85 MWh at $10, selling 100 MWh at $100."""
        spec = BatterySpec(power_mw=25.0, duration_hours=4.0,
                           round_trip_efficiency=0.85,
                           degradation_cost_per_mwh=0.0, soc_steps=40)
        expected = 100 * 100.0 - (100 / 0.85) * 10.0
        result = dispatch_day(two_price_day(10.0, 100.0), spec)
        assert result["revenue"] == pytest.approx(expected, rel=1e-6)

    def test_degradation_cost_is_charged_on_throughput(self):
        spec = BatterySpec(power_mw=25.0, duration_hours=4.0,
                           round_trip_efficiency=1.0,
                           degradation_cost_per_mwh=5.0, soc_steps=40)
        result = dispatch_day(two_price_day(10.0, 100.0), spec)
        # 200 MWh of throughput (100 in, 100 out) at $5 = $1,000 off $9,000.
        assert result["revenue"] == pytest.approx(8000.0, rel=1e-6)

    def test_degradation_suppresses_marginal_cycling(self):
        """A spread smaller than the wear cost should not be worked."""
        spec = BatterySpec(power_mw=25.0, duration_hours=4.0,
                           round_trip_efficiency=1.0,
                           degradation_cost_per_mwh=50.0, soc_steps=40)
        result = dispatch_day(two_price_day(45.0, 55.0), spec)
        assert result["throughput_mwh"] == pytest.approx(0.0)

    def test_revenue_is_never_negative(self):
        """Idling is always available, so the optimum cannot lose money."""
        rng = np.random.default_rng(0)
        for _ in range(20):
            prices = rng.normal(40, 60, 24)
            assert dispatch_day(prices, REALISTIC)["revenue"] >= -1e-9


class TestPhysicalConstraints:
    def _soc_path(self, schedule, spec):
        # schedule is positive on discharge, so SoC moves by the negative.
        return np.cumsum(-schedule)

    def test_state_of_charge_stays_within_bounds(self):
        rng = np.random.default_rng(1)
        prices = rng.normal(40, 50, 24)
        result = dispatch_day(prices, REALISTIC)
        soc = self._soc_path(result["schedule"], REALISTIC)
        assert soc.min() >= -1e-6
        assert soc.max() <= REALISTIC.energy_mwh + 1e-6

    def test_power_rating_is_respected_every_hour(self):
        result = dispatch_day(two_price_day(5.0, 200.0), REALISTIC)
        assert np.abs(result["schedule"]).max() <= REALISTIC.power_mw + 1e-6

    def test_battery_starts_and_ends_empty(self):
        result = dispatch_day(two_price_day(10.0, 100.0), LOSSLESS)
        soc = self._soc_path(result["schedule"], LOSSLESS)
        assert soc[-1] == pytest.approx(0.0, abs=1e-6)

    def test_cycles_reported_for_one_full_round_trip(self):
        result = dispatch_day(two_price_day(10.0, 100.0), LOSSLESS)
        assert result["cycles"] == pytest.approx(1.0, rel=1e-6)

    def test_empty_day_is_safe(self):
        assert dispatch_day(np.zeros(0), LOSSLESS)["revenue"] == 0.0


class TestAgainstTheHeuristic:
    """The top4-minus-bottom4 screen is not a bound in either direction.

    It silently assumes exactly one cycle a day with no losses, so it
    overstates value when efficiency and degradation bite, and understates it
    when prices swing more than once. Both directions are shown here because
    the write-up claims the model supersedes the screen, and that claim should
    rest on a demonstrated difference rather than an assertion.
    """

    @staticmethod
    def _screen(prices: np.ndarray) -> float:
        ordered = np.sort(prices)
        return (ordered[-4:].mean() - ordered[:4].mean()) * 100.0

    def test_matches_the_screen_on_a_single_cycle_day_without_losses(self):
        """One trough, one peak, no losses: the screen is exactly right."""
        prices = two_price_day(10.0, 100.0)
        assert dispatch_day(prices, LOSSLESS)["revenue"] == pytest.approx(
            self._screen(prices), rel=1e-6
        )

    def test_screen_understates_when_prices_swing_more_than_once(self):
        """A lossless battery works every swing, not just the daily one."""
        rng = np.random.default_rng(2)
        prices = rng.normal(40, 40, 24)
        result = dispatch_day(prices, LOSSLESS)
        assert result["revenue"] > self._screen(prices)
        assert result["cycles"] > 1.0   # more than the screen's implied cycle

    def test_screen_overstates_once_losses_and_wear_are_real(self):
        prices = two_price_day(10.0, 100.0)
        assert dispatch_day(prices, REALISTIC)["revenue"] < self._screen(prices)


class TestSeriesAndAggregation:
    def _frame(self, locations, days=2):
        rows = []
        for location in locations:
            for day in range(days):
                date = pd.Timestamp("2025-06-01").date() + pd.Timedelta(day, unit="D")
                for hour, price in enumerate(two_price_day(10.0, 100.0)):
                    rows.append({
                        "Location": location,
                        "local_date": date,
                        "interval_start_utc": pd.Timestamp("2025-06-01", tz="UTC")
                            + pd.Timedelta(day * 24 + hour, unit="h"),
                        "SPP": price,
                    })
        return pd.DataFrame(rows)

    def test_runs_per_location_day(self):
        out = dispatch_series(self._frame(["A", "B"]), LOSSLESS)
        assert len(out) == 4
        assert set(out["Location"]) == {"A", "B"}

    def test_short_day_is_skipped_not_optimised_against_holes(self):
        df = self._frame(["A"], days=1).head(5)
        assert dispatch_series(df, LOSSLESS).empty

    def test_null_price_day_is_skipped(self):
        df = self._frame(["A"], days=1)
        df.loc[0, "SPP"] = None
        assert dispatch_series(df, LOSSLESS).empty

    def test_annualise_scales_to_dollars_per_kw_year(self):
        daily = dispatch_series(self._frame(["A"]), LOSSLESS)
        out = annualise(daily, LOSSLESS)
        # $9,000/day over a 25,000 kW battery -> 9000*365/25000
        assert out["annual_per_kw"].iloc[0] == pytest.approx(9000 * 365 / 25000,
                                                             rel=1e-6)

    def test_decompose_splits_node_revenue_against_the_hub(self):
        node = dispatch_series(self._frame(["NODE_A"]), LOSSLESS)
        hub = dispatch_series(self._frame(["HB_WEST"]), LOSSLESS)
        hub["revenue"] *= 0.6          # hub earns less than the node
        out = decompose(node, hub)
        assert out["basis_revenue"].iloc[0] == pytest.approx(
            out["node_revenue"].iloc[0] * 0.4, rel=1e-6
        )
        assert out["basis_share"].iloc[0] == pytest.approx(0.4, rel=1e-6)

    def test_empty_inputs_are_safe(self):
        assert annualise(pd.DataFrame(), LOSSLESS).empty
        assert decompose(pd.DataFrame(), pd.DataFrame()).empty


class TestSpecValidation:
    def test_rejects_impossible_efficiency(self):
        with pytest.raises(ValueError, match="efficiency"):
            BatterySpec(round_trip_efficiency=1.5)

    def test_rejects_zero_power(self):
        with pytest.raises(ValueError, match="positive"):
            BatterySpec(power_mw=0)

    def test_energy_is_power_times_duration(self):
        assert BatterySpec(power_mw=10, duration_hours=4).energy_mwh == 40
