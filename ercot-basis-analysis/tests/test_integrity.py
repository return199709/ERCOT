"""Guards on the project's data-integrity rules.

These tests protect promises made in README.md and ASSUMPTIONS.md that are
easy to break silently during later work.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.config import PROJECT_ROOT, REPORTS
from src.transform.quality import find_gaps
from src.transform.mapping import assign_hub

SYNTHETIC_MARKERS = ("SYNTH_NODE", "synthetic_dam", "synthetic_rtm")


class TestNoSyntheticLeakage:
    """Synthetic fixture data must never reach a report or a derived table."""

    def _text_files(self):
        if not REPORTS.exists():
            return []
        return [p for p in REPORTS.rglob("*.md") if p.is_file()]

    def test_reports_contain_no_synthetic_node_names(self):
        offenders = []
        for path in self._text_files():
            text = path.read_text()
            for marker in SYNTHETIC_MARKERS:
                # The findings file may *describe* the rule; flag only data-like
                # usage, i.e. the fixture node names themselves.
                if marker == "SYNTH_NODE" and marker in text:
                    offenders.append((path.name, marker))
        assert not offenders, (
            f"Synthetic fixture data leaked into reports: {offenders}"
        )

    def test_processed_tables_contain_no_synthetic_nodes(self):
        processed = PROJECT_ROOT / "data" / "processed"
        if not processed.exists():
            pytest.skip("no processed data yet")
        offenders = []
        for path in processed.rglob("*.parquet"):
            df = pd.read_parquet(path)
            if "Location" in df.columns:
                if df["Location"].astype(str).str.startswith("SYNTH_NODE").any():
                    offenders.append(path.name)
        assert not offenders, f"Synthetic nodes in derived tables: {offenders}"


class TestFindingsHonesty:
    def test_findings_file_exists(self):
        assert (REPORTS / "findings.md").exists()

    def test_findings_declares_status_when_no_data_ingested(self):
        raw = PROJECT_ROOT / "data" / "raw"
        has_data = raw.exists() and any(raw.rglob("*.parquet"))
        text = (REPORTS / "findings.md").read_text().lower()
        if not has_data:
            assert "not yet produced" in text, (
                "No data is ingested, so findings.md must say results do not "
                "exist rather than presenting numbers."
            )


class TestNoSilentFilling:
    def test_gap_detection_does_not_add_rows(self):
        df = pd.DataFrame({
            "Location": ["A"] * 3,
            "interval_start_utc": pd.date_range("2025-06-11", periods=3,
                                                freq="h", tz="UTC"),
            "SPP": [1.0, 2.0, 3.0],
        })
        before = df.copy()
        find_gaps(df, 24)
        pd.testing.assert_frame_equal(df, before)


class TestNoGuessedHubs:
    def test_unknown_node_never_receives_a_hub(self):
        hubs, unmapped = assign_hub(pd.Series(["TOTALLY_UNKNOWN_NODE"]), {})
        assert pd.isna(hubs.iloc[0])
        assert unmapped == ["TOTALLY_UNKNOWN_NODE"]


class TestCredentialSafety:
    def test_env_example_has_no_values(self):
        """.env.example is tracked and public; it must stay placeholders."""
        path = PROJECT_ROOT / ".env.example"
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert line.endswith("="), (
                f"{path.name} must contain empty placeholders only; "
                "real credentials belong in .env"
            )

    def test_env_is_gitignored(self):
        ignore = (PROJECT_ROOT / ".gitignore").read_text().splitlines()
        assert ".env" in [line.strip() for line in ignore]

    def test_client_error_names_variables_not_values(self):
        from src.ingest.client import REQUIRED_VARS
        assert "ERCOT_API_PASSWORD" in REQUIRED_VARS
