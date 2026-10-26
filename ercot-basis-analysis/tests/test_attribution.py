"""Congestion attribution on constructed data.

EVERYTHING HERE IS SYNTHETIC. Basis series are built from known shift-factor
differences so the fit has a right answer to recover.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis import attribution

HOURS = 240
RNG = np.random.default_rng(7)


def _hours():
    return pd.date_range("2025-06-01", periods=HOURS, freq="h", tz="UTC")


def _shadow_prices(mu: dict[str, np.ndarray]) -> pd.DataFrame:
    """Long DAM shadow price table from per-constraint hourly series."""
    hours = _hours()
    rows = []
    for name, series in mu.items():
        for t, value in zip(hours, series):
            # The feed only carries rows for binding intervals.
            if value != 0:
                rows.append({"Constraint Name": name, "Interval Start": t,
                             "Shadow Price": float(value)})
    return pd.DataFrame(rows)


def _basis(series: dict[str, np.ndarray]) -> pd.DataFrame:
    hours = _hours()
    rows = []
    for name, values in series.items():
        for t, v in zip(hours, values):
            rows.append({"Location": name, "interval_start_utc": t, "basis": float(v)})
    return pd.DataFrame(rows)


@pytest.fixture
def world():
    """Two constraints; one binds half the hours, the other a third."""
    a = np.where(RNG.random(HOURS) < 0.5, RNG.uniform(50, 400, HOURS), 0.0)
    b = np.where(RNG.random(HOURS) < 0.33, RNG.uniform(20, 200, HOURS), 0.0)
    mu = {"SYNTH_TIE_A": a, "SYNTH_TIE_B": b}
    # Node W sits behind A (discount), node E is on the import side of B.
    noise = RNG.normal(0, 0.5, HOURS)
    basis = {
        "SYNTH_NODE_W": -0.08 * a + 0.01 * b + noise,
        "SYNTH_NODE_E": 0.02 * a + 0.15 * b + noise,
        "SYNTH_NODE_FLAT": np.zeros(HOURS) + noise,
    }
    return mu, basis


class TestMatrix:
    def test_non_binding_hours_are_zero_not_missing(self, world):
        """The feed has no row for a congestion-free hour; the matrix must."""
        mu, _ = world
        hours = _hours()
        wide = attribution.shadow_price_matrix(_shadow_prices(mu), top_k=10,
                                               min_bound_hours=1, hours=hours)
        assert set(wide.columns) == {"SYNTH_TIE_A", "SYNTH_TIE_B"}
        assert not wide.isna().any().any()
        # Every hour inside the feed's span is present, zeros included.
        first_bound = hours[(mu["SYNTH_TIE_A"] != 0) | (mu["SYNTH_TIE_B"] != 0)]
        expected = hours[(hours >= first_bound.min()) & (hours <= first_bound.max())]
        assert len(wide) == len(expected)
        a_zero_in_span = int((mu["SYNTH_TIE_A"][hours.isin(expected)] == 0).sum())
        assert (wide["SYNTH_TIE_A"] == 0).sum() == a_zero_in_span

    def test_hours_outside_the_feed_span_are_not_invented(self, world):
        mu, _ = world
        hours = _hours()
        extended = hours.union(pd.date_range(hours[-1] + pd.Timedelta(1, unit="h"),
                                             periods=48, freq="h", tz="UTC"))
        wide = attribution.shadow_price_matrix(_shadow_prices(mu), top_k=10,
                                               min_bound_hours=1, hours=extended)
        assert wide.index.max() <= hours[-1]

    def test_rarely_binding_constraints_are_dropped(self, world):
        mu, _ = world
        mu = dict(mu)
        rare = np.zeros(HOURS)
        rare[:3] = 999.0
        mu["SYNTH_RARE"] = rare
        wide = attribution.shadow_price_matrix(_shadow_prices(mu), top_k=10,
                                               min_bound_hours=24)
        assert "SYNTH_RARE" not in wide.columns

    def test_top_k_keeps_the_costliest(self, world):
        mu, _ = world
        wide = attribution.shadow_price_matrix(_shadow_prices(mu), top_k=1,
                                               min_bound_hours=1)
        assert list(wide.columns) == ["SYNTH_TIE_A"]

    def test_empty_input(self):
        assert attribution.shadow_price_matrix(pd.DataFrame()).empty


class TestFit:
    def test_recovers_known_shift_factor_differences(self, world):
        mu, basis = world
        by_node, contrib, _ = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        coef = contrib.set_index(["Location", "constraint"])["coefficient"]
        assert coef["SYNTH_NODE_W", "SYNTH_TIE_A"] == pytest.approx(-0.08, abs=0.01)
        assert coef["SYNTH_NODE_W", "SYNTH_TIE_B"] == pytest.approx(0.01, abs=0.01)
        assert coef["SYNTH_NODE_E", "SYNTH_TIE_B"] == pytest.approx(0.15, abs=0.01)

    def test_dominant_constraint_is_named(self, world):
        mu, basis = world
        by_node, _, _ = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        dom = by_node.set_index("Location")["dominant_constraint"]
        assert dom["SYNTH_NODE_W"] == "SYNTH_TIE_A"
        assert dom["SYNTH_NODE_E"] == "SYNTH_TIE_B"

    def test_r2_high_when_structure_holds_and_low_when_it_does_not(self, world):
        mu, basis = world
        by_node, _, _ = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        r2 = by_node.set_index("Location")["r2"]
        assert r2["SYNTH_NODE_W"] > 0.95
        assert r2["SYNTH_NODE_E"] > 0.95
        # Pure noise: the constraints explain nothing.
        assert r2["SYNTH_NODE_FLAT"] < 0.2

    def test_contributions_sum_to_explained_mean(self, world):
        mu, basis = world
        by_node, contrib, _ = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        summed = contrib.groupby("Location")["contribution"].sum()
        for _, row in by_node.iterrows():
            assert summed[row["Location"]] == pytest.approx(row["explained_mean"], abs=1e-9)
            assert row["mean_basis"] - row["explained_mean"] == pytest.approx(
                row["residual_mean"], abs=1e-9)

    def test_by_constraint_counts_dominated_nodes(self, world):
        mu, basis = world
        _, _, by_constraint = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        counts = by_constraint.set_index("constraint")["nodes_dominated"]
        assert counts["SYNTH_TIE_A"] == 1   # node W
        assert counts["SYNTH_TIE_B"] == 1   # node E
        # The flat node's basis is noise around zero: below the materiality
        # floor, so it dominates nothing even though it has a largest term.
        assert counts.sum() == 2

    def test_nodes_affected_ignores_immaterial_coefficients(self, world):
        mu, basis = world
        _, _, by_constraint = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        affected = by_constraint.set_index("constraint")["nodes_affected"]
        # A touches W (-0.08) and E (+0.02) materially; B only E (+0.15).
        # W's +0.01 on B and the flat node's noise are below the floor.
        assert affected["SYNTH_TIE_A"] == 2
        assert affected["SYNTH_TIE_B"] == 1

    def test_short_node_is_skipped_not_fitted(self, world):
        mu, basis = world
        short = _basis(basis)
        short = short[~((short["Location"] == "SYNTH_NODE_E")
                        & (short["interval_start_utc"] >= _hours()[30]))]
        by_node, _, _ = attribution.attribute(
            short, _shadow_prices(mu), top_k=10, min_bound_hours=1, min_hours=100,
        )
        assert "SYNTH_NODE_E" not in set(by_node["Location"])
        assert "SYNTH_NODE_W" in set(by_node["Location"])

    def test_ridge_shrinks_toward_zero(self, world):
        mu, basis = world
        kwargs = dict(top_k=10, min_bound_hours=1, min_hours=24)
        _, plain, _ = attribution.attribute(_basis(basis), _shadow_prices(mu), **kwargs)
        _, ridged, _ = attribution.attribute(_basis(basis), _shadow_prices(mu),
                                             ridge=1e6, **kwargs)
        p = plain.set_index(["Location", "constraint"])["coefficient"]
        r = ridged.set_index(["Location", "constraint"])["coefficient"]
        key = ("SYNTH_NODE_W", "SYNTH_TIE_A")
        assert abs(r[key]) < abs(p[key])

    def test_no_shadow_prices_returns_empty_frames(self, world):
        _, basis = world
        by_node, contrib, by_constraint = attribution.attribute(
            _basis(basis), pd.DataFrame())
        assert by_node.empty and contrib.empty and by_constraint.empty
        assert list(by_node.columns) == attribution.BY_NODE_COLUMNS

    def test_top_contributions_for_drilldown(self, world):
        mu, basis = world
        _, contrib, _ = attribution.attribute(
            _basis(basis), _shadow_prices(mu), top_k=10, min_bound_hours=1,
            min_hours=24,
        )
        top = attribution.top_contributions(contrib, "SYNTH_NODE_W", n=1)
        assert len(top) == 1
        assert top.iloc[0]["constraint"] == "SYNTH_TIE_A"
