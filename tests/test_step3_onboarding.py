"""Tests for RevenueLens onboarding pipeline."""

import os

import psycopg
import pytest
from psycopg.errors import ReadOnlySqlTransaction


@pytest.fixture(scope="module")
def dsn() -> str:
    """Get database URL from environment and verify connectivity."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(url) as conn:
            conn.execute("SELECT 1")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Cannot connect to database: {e}")
    from legacy_sim.__main__ import main as sim_main

    sim_main(["load", "--database-url", url])
    return url


def test_adapter_readonly(dsn: str) -> None:
    """Test read-only adapter functionality."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        tables = adapter.list_tables()
        assert "bill_hdr" in tables
        assert len(tables) == 13

        # Query should work
        rows = adapter.query("SELECT 1 AS x")
        assert rows[0]["x"] == 1

        # Non-SELECT should raise
        with pytest.raises(ValueError):
            adapter.query("DELETE FROM nimbus.cust_mstr")

        # Direct execution should fail with read-only error
        with pytest.raises(ReadOnlySqlTransaction):
            adapter.conn.execute("DELETE FROM nimbus.cust_mstr")
        adapter.conn.rollback()


def test_discover(dsn: str) -> None:
    """Test schema discovery."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        profile = discover(adapter)

        # cust_no should be candidate key in cust_mstr
        cust_profile = profile.tables["cust_mstr"]
        assert "cust_no" in cust_profile.candidate_keys

        # Should find join from subscr_mstr.cust_no to cust_mstr.cust_no
        joins = profile.joins
        found = False
        for j in joins:
            if (j.left_table == "subscr_mstr" and j.left_col == "cust_no"
                    and j.right_table == "cust_mstr" and j.right_col == "cust_no"):
                found = True
                assert j.overlap >= 0.5
                break
        assert found, "Expected join subscr_mstr.cust_no -> cust_mstr.cust_no"


def test_heuristic_map(dsn: str) -> None:
    """Test heuristic mapping."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.mapping import heuristic_map

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        profile = discover(adapter)
        mapping = heuristic_map(profile)

        # Check table mappings
        assert mapping.table("invoice") == "bill_hdr"
        assert mapping.table("invoice_line") == "bill_dtl"
        assert mapping.table("rated_event") == "rtd_evt"
        assert mapping.table("usage") == "usg_cdr"
        assert mapping.table("plan") == "rt_plan_cfg"
        assert mapping.table("rate") == "trf_rate_cfg"
        assert mapping.table("contract") == "contract_terms"
        assert mapping.table("payment") == "pymt_txn"
        assert mapping.table("subscription") == "subscr_mstr"
        assert mapping.table("subscription_discount") == "subscr_disc"
        assert mapping.table("discount") == "disc_cfg"

        # Check column mappings
        assert mapping.column("invoice", "total") == "tot_amt"
        assert mapping.column("contract", "agreed_fee") == "agreed_mthly_fee"


def test_learn_catalog(dsn: str) -> None:
    """Test rule learning from config."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.learning import learn_catalog
    from app.mapping import heuristic_map

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        profile = discover(adapter)
        mapping = heuristic_map(profile)
        catalog = learn_catalog(adapter, mapping)

        rule = catalog.get("plan_fee", "NMB_BASIC_199")
        assert rule is not None
        assert rule.value == 199.0
        assert rule.source.startswith("config:")


def test_replay(dsn: str) -> None:
    """Test bill replay."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.learning import learn_catalog
    from app.mapping import heuristic_map
    from app.replay import replay_bills

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        profile = discover(adapter)
        mapping = heuristic_map(profile)
        catalog = learn_catalog(adapter, mapping)
        result = replay_bills(adapter, mapping, catalog)

        # Total invoices should match bill_hdr count
        assert result.total == profile.tables["bill_hdr"].row_count
        assert result.match_rate >= 0.9
        assert len(result.mismatches()) >= 1


def test_llm_refine_fake(dsn: str) -> None:
    """Test LLM refinement with FakeLLM."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.llm import FakeLLM
    from app.mapping import heuristic_map, llm_refine

    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        profile = discover(adapter)
        mapping = heuristic_map(profile)

        # FakeLLM with empty response should not change mapping
        llm = FakeLLM()
        refined = llm_refine(mapping, profile, llm)
        assert refined is mapping

        # FakeLLM with invalid column suggestion should not apply
        llm2 = FakeLLM(['{"fields":[{"entity":"invoice","field":"total","column":"no_such_col","confidence":0.99}]}'])
        refined2 = llm_refine(mapping, profile, llm2)
        # Column should remain unchanged
        assert refined2.column("invoice", "total") == "tot_amt"


def test_onboard(dsn: str) -> None:
    """Test full onboarding pipeline."""
    from app.llm import FakeLLM
    from app.onboard import onboard

    result = onboard(dsn, "nimbus", FakeLLM())
    assert result["replay"]["match_rate"] >= 0.9
    assert result["tables"] == 13
    assert result["rules"] > 0
