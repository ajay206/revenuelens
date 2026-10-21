"""Unit tests for app.explain (step 5)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app.explain import (
    Story,
    match_tickets,
    explain_finding,
    explain_all,
    to_markdown,
)
from app.llm import FakeLLM
from app.reconcile import Finding

# ---------------------------------------------------------------------------
# Helper data
# ---------------------------------------------------------------------------

_SAMPLE_TICKETS = [
    {
        "key": "T-001",
        "title": "Rating engine missing data",
        "labels": ["rating", "data"],
    },
    {
        "key": "T-002",
        "title": "Billing cycle not invoiced",
        "labels": ["billing"],
    },
    {
        "key": "T-003",
        "title": "Tariff table mismatch discovered",
        "labels": ["tariff"],
    },
    {
        "key": "T-004",
        "title": "Discount expiry not handled",
        "labels": ["discount/expiry"],
    },
    {
        "key": "T-005",
        "title": "Provisioning step skipped",
        "labels": ["provisioning"],
    },
    {
        "key": "T-006",
        "title": "Renewal reminder missed",
        "labels": ["renewal"],
    },
    {
        "key": "T-007",
        "title": "Unmatched payment detected",
        "labels": ["payment"],
    },
    {
        "key": "T-008",
        "title": "Duplicate charge found",
        "labels": ["duplicate"],
    },
]

def _make_finding(check: str) -> Finding:
    return Finding(
        check=check,
        record_ids=["r1", "r2"],
        table="revenue",
        customer_id="CUST123",
        period="2024-07",
        impact=-1500.75,
        evidence={},
        description=f"Finding for {check}",
    )

# ---------------------------------------------------------------------------
# match_tickets tests – one per mapping keyword
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "check,expected_key",
    [
        ("unrated_usage", "rating"),
        ("rated_not_invoiced", "billing"),
        ("tariff_mismatch", "tariff"),
        ("expired_discount", "discount/expiry"),
        ("provisioned_not_billed", "provisioning"),
        ("missed_renewal", "renewal"),
        ("unmatched_payment", "payment"),
        ("duplicate_charge", "duplicate"),
    ],
)
def test_match_tickets_maps_correctly(check: str, expected_key: str):
    f = _make_finding(check)
    matches = match_tickets(f, _sample_tickets)
    assert any(expected_key in (t["title"].lower() + " " + " ".join(t["labels"])) for t in matches)


# ---------------------------------------------------------------------------
# explain_finding – happy path
# ---------------------------------------------------------------------------

def test_explain_finding_happy_path():
    f = _make_finding("unrated_usage")
    llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "title": "Unrated usage detected",
                    "what": "Usage records without rating.",
                    "since_when": "2024-07",
                    "root_cause": "Rating job failed.",
                    "who_affected": "All customers with usage in July.",
                    "what_to_do": "Re‑run rating batch.",
                }
            )
        ]
    )
    story = explain_finding(f, _sample_tickets, llm)

    # deterministic fields
    assert story.money_impact == 1500.75
    assert story.check == "unrated_usage"
    assert any(c["type"] == "record" and c["ref"] == "revenue:r1" for c in story.citations)
    assert any(c["type"] == "ticket" and c["ref"] == "T-001" for c in story.citations)

    # LLM‑provided fields
    assert story.title == "Unrated usage detected"
    assert story.what == "Usage records without rating."
    assert story.confidence == "high"

# ---------------------------------------------------------------------------
# explain_finding – LLM returns garbage
# ---------------------------------------------------------------------------

def test_explain_finding_fallback_on_garbage():
    f = _make_finding("rated_not_invoiced")
    llm = FakeLLM(responses=["not a json {}"])
    story = explain_finding(f, _sample_tickets, llm)

    # fallback template should be used
    assert "Rated Not Invoiced" in story.title
    assert story.confidence == "needs confirmation"
    # money impact still deterministic
    assert story.money_impact == 1500.75

# ---------------------------------------------------------------------------
# Money impact must stay deterministic even if LLM tries to override
# ---------------------------------------------------------------------------

def test_money_impact_is_not_overridden_by_llm():
    f = _make_finding("tariff_mismatch")
    llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "title": "Tariff mismatch",
                    "what": "Bad tariff",
                    "since_when": "2025-01",
                    "root_cause": "Config error",
                    "who_affected": "N/A",
                    "what_to_do": "Fix config",
                    "money_impact": 9999,  # should be ignored
                }
            )
        ]
    )
    story = explain_finding(f, _sample_tickets, llm)
    assert story.money_impact == 1500.75  # from finding.impact


# ---------------------------------------------------------------------------
# citations include every record and every matched ticket
# ---------------------------------------------------------------------------

def test_citations_include_all_sources():
    f = _make_finding("duplicate_charge")
    llm = FakeLLM(responses=["{}"])
    story = explain_finding(f, _sample_tickets, llm)
    # two record citations
    assert len([c for c in story.citations if c["type"] == "record"]) == 2
    # one ticket citation (T-008 matches duplicate)
    assert any(c["type"] == "ticket" and c["ref"] == "T-008" for c in story.citations)


# ---------------------------------------------------------------------------
# to_markdown contains Sources section
# ---------------------------------------------------------------------------

def test_to_markdown_contains_sources():
    f1 = _make_finding("unrated_usage")
    f2 = _make_finding("missed_renewal")
    llm = FakeLLM(responses=[json.dumps({}), json.dumps({})])
    stories = explain_all([f1, f2], _sample_tickets, llm)
    md = to_markdown(stories)
    assert "Sources" in md
    assert md.count("Sources") == 2


# ---------------------------------------------------------------------------
# Integration test against a real database (skipped if unavailable)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    # attempt simple connection test
    try:
        import psycopg  # type: ignore

        with psycopg.connect(url) as conn:
            conn.close()
    except Exception:
        pytest.skip("Database not reachable")
    return url


@pytest.fixture(scope="module")
def loaded_findings(db_url: str) -> list[Finding]:
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.mapping import map_schema

    with ReadOnlyAdapter(db_url, "nimbus") as adapter:
        mapping = map_schema(discover(adapter))
        from app.reconcile import run_checks

        return run_checks(adapter, mapping)


def test_db_findings_all_have_story(db_url: str, loaded_findings: list[Finding]):
    llm = FakeLLM(responses=["{}"] * len(loaded_findings))
    stories = explain_all(loaded_findings, _sample_tickets, llm)
    for s in stories:
        # at least one record citation must exist
        assert any(c["type"] == "record" for c in s.citations)
        # confidence may be low because we use dummy LLM, but story must be built
        assert isinstance(s.title, str) and s.title
