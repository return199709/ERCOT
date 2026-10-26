"""Zone inheritance through identical price series (synthetic data).

EVERYTHING HERE IS SYNTHETIC. The frames are built to exercise the rule, not
to describe any real settlement point.
"""

import pandas as pd

from src.transform.mapping import extend_zone_map_by_shared_series


def _frame(series: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for location, values in series.items():
        for hour, value in enumerate(values):
            rows.append({
                "Location": location,
                "interval_start_utc": pd.Timestamp("2025-06-01", tz="UTC")
                    + pd.Timedelta(hour, unit="h"),
                "SPP": value,
            })
    return pd.DataFrame(rows)


RAMP = [float(v) for v in range(30)]
OTHER = [float(v) + 0.5 for v in range(30)]


class TestRecovery:
    def test_unmapped_twin_inherits_zone(self):
        prices = _frame({"SYNTH_RN": RAMP, "SYNTH_CC1": RAMP})
        zones, prov = extend_zone_map_by_shared_series({"SYNTH_RN": "LZ_WEST"}, prices)
        assert zones["SYNTH_CC1"] == "LZ_WEST"
        assert zones["SYNTH_RN"] == "LZ_WEST"  # untouched
        row = prov.set_index("Location").loc["SYNTH_CC1"]
        assert row["status"] == "recovered"
        assert row["inherited_from"] == "SYNTH_RN"
        assert row["intervals"] == 30

    def test_mapped_members_are_never_rewritten(self):
        prices = _frame({"SYNTH_A": RAMP, "SYNTH_B": RAMP})
        zones, prov = extend_zone_map_by_shared_series(
            {"SYNTH_A": "LZ_WEST", "SYNTH_B": "LZ_NORTH"}, prices
        )
        assert zones == {"SYNTH_A": "LZ_WEST", "SYNTH_B": "LZ_NORTH"}
        assert prov.empty

    def test_conflicting_zones_recover_nothing(self):
        """Two mapped twins in different zones: the series tells us nothing safe."""
        prices = _frame({"SYNTH_A": RAMP, "SYNTH_B": RAMP, "SYNTH_X": RAMP})
        zones, prov = extend_zone_map_by_shared_series(
            {"SYNTH_A": "LZ_WEST", "SYNTH_B": "LZ_NORTH"}, prices
        )
        assert "SYNTH_X" not in zones
        assert prov.set_index("Location").loc["SYNTH_X", "status"] == "skipped_zone_conflict"

    def test_group_without_a_mapped_member_recovers_nothing(self):
        prices = _frame({"SYNTH_X": RAMP, "SYNTH_Y": RAMP})
        zones, prov = extend_zone_map_by_shared_series({}, prices)
        assert zones == {}
        assert set(prov["status"]) == {"skipped_no_mapped_member"}
        assert set(prov["Location"]) == {"SYNTH_X", "SYNTH_Y"}

    def test_different_series_are_not_linked(self):
        prices = _frame({"SYNTH_RN": RAMP, "SYNTH_CC1": OTHER})
        zones, prov = extend_zone_map_by_shared_series({"SYNTH_RN": "LZ_WEST"}, prices)
        assert "SYNTH_CC1" not in zones
        assert prov.empty

    def test_hubs_and_zones_in_a_group_are_ignored(self):
        """Only resource nodes inherit; a hub pricing with a node is not a node."""
        prices = _frame({"HB_WEST": RAMP, "SYNTH_CC1": RAMP, "SYNTH_RN": RAMP})
        zones, prov = extend_zone_map_by_shared_series({"SYNTH_RN": "LZ_WEST"}, prices)
        assert zones["SYNTH_CC1"] == "LZ_WEST"
        assert "HB_WEST" not in zones

    def test_empty_prices(self):
        zones, prov = extend_zone_map_by_shared_series({"A": "LZ_WEST"}, _frame({}))
        assert zones == {"A": "LZ_WEST"}
        assert prov.empty
