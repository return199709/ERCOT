"""Tests for the diverging colour scale."""

import pandas as pd

from app.colors import NEUTRAL, diverging, symmetric_bound, text_colour


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


class TestDiverging:
    def test_zero_is_the_neutral_midpoint(self):
        """The whole point of a diverging scale: 0 must be neutral."""
        assert diverging(0.0, 50.0) == _hex(NEUTRAL)

    def test_negative_and_positive_differ(self):
        assert diverging(-25.0, 50.0) != diverging(25.0, 50.0)

    def test_symmetric_values_are_equidistant_from_neutral(self):
        assert diverging(-50.0, 50.0) == "#b2182b"
        assert diverging(50.0, 50.0) == "#2166ac"

    def test_beyond_bound_is_clamped(self):
        assert diverging(-999.0, 50.0) == diverging(-50.0, 50.0)

    def test_nan_and_none_are_transparent(self):
        assert diverging(float("nan"), 50.0) == "transparent"
        assert diverging(None, 50.0) == "transparent"

    def test_zero_bound_is_safe(self):
        assert diverging(1.0, 0.0) == "transparent"


class TestSymmetricBound:
    def test_uses_largest_absolute_value(self):
        assert symmetric_bound(pd.Series([-30.0, 10.0])) == 30.0

    def test_all_nan_returns_zero(self):
        assert symmetric_bound(pd.Series([float("nan")])) == 0.0


class TestTextColour:
    def test_light_ink_on_saturated_cells(self):
        assert text_colour(-45.0, 50.0) == "#ffffff"

    def test_dark_ink_near_neutral(self):
        assert text_colour(1.0, 50.0) == "#1a1a1a"
