"""Tests for the preflight checks (synthetic frames; no network)."""

import pandas as pd
import pytest

from src.ingest.preflight import (
    FAIL, PASS, WARN, COLUMN_CONTRACTS, MAPPING_CONTRACTS,
    check_credentials, check_host, validate_columns,
)


class TestCheckCredentials:
    @pytest.fixture(autouse=True)
    def no_dotenv(self, monkeypatch):
        """Stop check_credentials loading a real .env over the test's env.

        These tests exercise the missing-variable logic, not python-dotenv.
        """
        monkeypatch.setattr("src.ingest.preflight.load_dotenv", lambda *a, **k: None)

    def test_reports_missing_variable_names_not_values(self, monkeypatch):
        monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
        monkeypatch.setenv("ERCOT_API_USERNAME", "someone@example.com")
        monkeypatch.setenv("ERCOT_PUBLIC_API_SUBSCRIPTION_KEY", "secret-value-here")
        status, detail = check_credentials()
        assert status == FAIL
        assert "ERCOT_API_PASSWORD" in detail
        # The guarantee that matters: no value ever appears in the message.
        assert "secret-value-here" not in detail
        assert "someone@example.com" not in detail

    def test_passes_when_all_set(self, monkeypatch):
        for name in ("ERCOT_API_USERNAME", "ERCOT_API_PASSWORD",
                     "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY"):
            monkeypatch.setenv(name, "x")
        status, _ = check_credentials()
        assert status == PASS

    def test_empty_string_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("ERCOT_API_USERNAME", "x")
        monkeypatch.setenv("ERCOT_API_PASSWORD", "")
        monkeypatch.setenv("ERCOT_PUBLIC_API_SUBSCRIPTION_KEY", "x")
        status, detail = check_credentials()
        assert status == FAIL
        assert "ERCOT_API_PASSWORD" in detail


class TestValidateColumns:
    def test_recognises_expected_spp_columns(self):
        df = pd.DataFrame(columns=["Location", "SPP", "Interval Start"])
        results = validate_columns("dam_spp", df)
        assert results and all(s == PASS for s, _, _ in results)

    def test_missing_required_column_fails_and_lists_actuals(self):
        df = pd.DataFrame(columns=["SettlementPointName", "Price"])
        results = validate_columns("dam_spp", df)
        statuses = [s for s, _, _ in results]
        assert FAIL in statuses
        joined = " ".join(d for _, _, d in results)
        assert "SettlementPointName" in joined  # actuals surfaced for fixing

    def test_optional_column_warns_rather_than_fails(self):
        df = pd.DataFrame(columns=["Nothing", "Useful"])
        results = validate_columns("wind_by_region", df)
        assert [s for s, _, _ in results] == [WARN]

    def test_alternate_spelling_accepted(self):
        df = pd.DataFrame(columns=["ConstraintName", "ShadowPrice", "Timestamp"])
        results = validate_columns("dam_shadow_prices", df)
        assert all(s == PASS for s, _, _ in results)

    def test_unknown_dataset_yields_no_contracts(self):
        assert validate_columns("not_a_dataset", pd.DataFrame()) == []


class TestContractsCoverPipeline:
    def test_every_price_dataset_has_required_contracts(self):
        for dataset in ("dam_spp", "rtm_spp"):
            concepts = {c for n, c, _, _ in COLUMN_CONTRACTS if n == dataset}
            assert {"settlement point", "price", "interval start"} <= concepts

    def test_shadow_price_contracts_reuse_the_analysis_candidate_lists(self):
        """The check must validate the same lists the code actually uses."""
        from src.analysis import constraints
        entry = next(c for n, cpt, c, _ in COLUMN_CONTRACTS
                     if n == "dam_shadow_prices" and cpt == "shadow price"
                     for c in [c])
        assert entry is constraints.SHADOW_PRICE_CANDIDATES

    def test_mapping_contracts_cover_point_and_zone(self):
        assert {c for c, _ in MAPPING_CONTRACTS} == {"settlement point", "load zone"}


class TestCheckHost:
    def test_unresolvable_host_fails_with_dns_detail(self):
        status, detail = check_host("no-such-host.invalid", timeout=2.0)
        assert status == FAIL
        assert "DNS" in detail

    def test_checks_the_proxied_path_not_a_raw_socket(self):
        """A raw socket bypasses HTTPS_PROXY and would falsely report success.

        gridstatus uses requests, which honours the proxy, so the check must
        too -- otherwise preflight passes and every real fetch then fails.
        """
        status, detail = check_host("api.ercot.com", timeout=8.0)
        if status == FAIL:
            assert any(w in detail.lower() for w in ("proxy", "egress", "dns",
                                                     "reach", "tls"))
        else:
            assert "HTTP" in detail  # proved by an actual response
