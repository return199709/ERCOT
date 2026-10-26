"""Constraint dictionary on synthetic shadow price rows.

EVERYTHING HERE IS SYNTHETIC. Station names are invented.
"""

import pandas as pd

from src.analysis import constraint_dictionary as cd


def _dam():
    ts = pd.date_range("2025-06-01", periods=4, freq="h", tz="UTC")
    return pd.DataFrame({
        "Interval Start": ts,
        "Constraint ID": [1, 1, 1, 2],
        "Constraint Name": ["9999__X", "9999__X", "9999__X", "SYN_TIE_1"],
        "Contingency Name": ["SYN_CTG_A", "SYN_CTG_A", "SYN_CTG_B", "BASE CASE"],
        "Limiting Facility": ["SYN_LINE 345", "SYN_LINE 345", "SYN_LINE 345", pd.NA],
        "Constraint Limit": [900.0, 905.0, 880.0, 400.0],
        "Shadow Price": [100.0, 50.0, 20.0, 10.0],
        "From Station": ["SYN_NORTH", "SYN_NORTH", "SYN_NORTH", "SYN_WEST"],
        "To Station": ["SYN_SOUTH", "SYN_SOUTH", "SYN_SOUTH", pd.NA],
        "From Station kV": [345.0, 345.0, 345.0, 138.0],
        "To Station kV": [345.0, 345.0, 345.0, pd.NA],
    })


def _sced():
    ts = pd.date_range("2025-06-01", periods=2, freq="5min", tz="UTC")
    return pd.DataFrame({
        "SCED Timestamp": ts,
        "Constraint Name": ["9999__X", "SYN_ONLY_RT"],
        "Shadow Price": [60.0, 5.0],
        "From Station": ["SYN_NORTH", "SYN_EAST"],
        "To Station": ["SYN_SOUTH", "SYN_EAST2"],
        "From Station kV": [345.0, 69.0],
        "To Station kV": [345.0, 69.0],
    })


class TestBuild:
    def test_one_row_per_constraint_across_markets(self):
        d = cd.build(_dam(), _sced())
        assert sorted(d["constraint"]) == ["9999__X", "SYN_ONLY_RT", "SYN_TIE_1"]
        row = d.set_index("constraint").loc["9999__X"]
        assert row["markets"] == "DAM+SCED"
        assert row["rows"] == 4

    def test_label_names_the_element(self):
        d = cd.build(_dam(), None).set_index("constraint")
        assert d.loc["9999__X", "element"] == "SYN_NORTH 345 kV -> SYN_SOUTH 345 kV (SYN_LINE 345)"
        # One-ended with no facility: just the station.
        assert d.loc["SYN_TIE_1", "element"] == "SYN_WEST 138 kV"

    def test_mode_and_contingency_count(self):
        d = cd.build(_dam(), None).set_index("constraint")
        assert d.loc["9999__X", "top_contingency"] == "SYN_CTG_A"
        assert d.loc["9999__X", "n_contingencies"] == 2
        assert d.loc["9999__X", "constraint_limit_min"] == 880.0
        assert d.loc["9999__X", "constraint_limit_max"] == 905.0

    def test_missing_attribute_columns_are_tolerated(self):
        bare = pd.DataFrame({"Constraint Name": ["SYN_BARE"], "Shadow Price": [1.0]})
        d = cd.build(bare, None)
        assert d.loc[0, "element"] == "SYN_BARE"   # falls back to the name
        assert pd.isna(d.loc[0, "from_station"])

    def test_empty_inputs(self):
        assert cd.build(None, None).empty
        assert list(cd.build(pd.DataFrame(), pd.DataFrame()).columns) == cd.COLUMNS


class TestAttach:
    def test_label_placed_next_to_name_and_unknowns_keep_their_name(self):
        d = cd.build(_dam(), None)
        ranked = pd.DataFrame({"constraint": ["9999__X", "SYN_UNSEEN"],
                               "total_cost": [10.0, 5.0]})
        out = cd.attach(ranked, d)
        assert list(out.columns) == ["constraint", "element", "total_cost"]
        assert out.loc[0, "element"].startswith("SYN_NORTH")
        assert out.loc[1, "element"] == "SYN_UNSEEN"

    def test_custom_column_names(self):
        d = cd.build(_dam(), None)
        nodes = pd.DataFrame({"Location": ["SYNTH_NODE"], "dominant_constraint": ["9999__X"]})
        out = cd.attach(nodes, d, on="dominant_constraint", out="dominant_element")
        assert out.loc[0, "dominant_element"].startswith("SYN_NORTH")

    def test_empty_dictionary_still_populates(self):
        ranked = pd.DataFrame({"constraint": ["A"]})
        out = cd.attach(ranked, pd.DataFrame(columns=cd.COLUMNS))
        assert out.loc[0, "element"] == "A"
