"""Unit and integration tests for Step 9: Reports and Docs."""

from __future__ import annotations

import csv
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from app.docgen import (
    Doc,
    KnowledgeBase,
    classify,
    doc_to_dict,
    generate_doc,
    to_confluence_storage,
    to_markdown,
    to_pdf,
    write_confluence_draft,
)
from app.learning import Rule
from app.main import app
from app.reconcile import Finding
from app.reports import findings_to_csv, findings_to_pdf

# --------------------------------------------------------------------------- #
# Fixtures for unit tests (no DB)
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_rules() -> list[Rule]:
    return [
        Rule("R0001", "plan_fee", "NMB_MAX_699", 699.0, "config:plan[id=1]", 1.0),
        Rule("R0002", "included_data", "NMB_MAX_699", 10000.0, "config:plan[id=1]", 1.0),
        Rule("R0003", "overage_rate", "NMB_MAX_699", 0.05, "config:plan[id=1]", 1.0),
        Rule("R0004", "usage_rate", "NMB_MAX_699:DATA", 0.01, "config:rate[id=1]", 1.0),
        Rule("R0005", "usage_rate", "NMB_MAX_699:VOICE", 0.50, "config:rate[id=2]", 0.9),  # low confidence
        Rule("R0006", "observed_fee", "NMB_MAX_699", 699.0, "billed:invoice_line n=50", 0.98),
        Rule("R0007", "discount_pct", "DISC10", 10.0, "config:discount[id=1]", 1.0),
        Rule("R0008", "discount_window", "DISC10", "2024-01-01..2024-12-31", "config:discount[id=1]", 1.0),
        Rule("R0009", "plan_fee", "NMB_MAX_999", 999.0, "config:plan[id=2]", 1.0),
    ]


@pytest.fixture
def sample_findings() -> list[Finding]:
    return [
        Finding(
            check="expired_discount",
            record_ids=["r1", "r2"],
            table="invoice_line",
            customer_id="C001",
            period="2024-01",
            impact=-500.0,
            evidence={},
            description="Discount DISC10 expired but still applied",
        ),
        Finding(
            check="rated_not_invoiced",
            record_ids=["r3"],
            table="rating",
            customer_id="C002",
            period="2024-01",
            impact=-1200.0,
            evidence={},
            description="Rated usage not on invoice",
        ),
        Finding(
            check="duplicate_charge",
            record_ids=["r4", "r5", "r6"],
            table="invoice_line",
            customer_id="C003",
            period="2024-01",
            impact=-300.0,
            evidence={},
            description="Duplicate RECUR charge",
        ),
    ]


@pytest.fixture
def sample_tickets() -> list[dict]:
    return [
        {
            "key": "NIM-101",
            "source": "jira",
            "title": "Discount DISC10 applied at 10% but should be 15%",
            "created": "2026-07-05T10:00:00",
            "description": "Ticket raised after audit; discount percentage mismatch.",
            "labels": ["discount", "config"],
        },
        {
            "key": "NIM-102",
            "source": "ado",
            "title": "Increase NMB_MAX_699 fee to 749 from 2026-08-01",
            "created": "2026-06-20T10:00:00",
            "description": "Planned price increase not reflected in RT_PLAN_CFG.",
            "labels": ["plan", "price", "config"],
        },
        {
            "key": "NIM-201",
            "source": "jira",
            "title": "CDR rating failure for DATA usage",
            "created": "2026-07-10T10:00:00",
            "description": "Some DATA CDRs not rated due to missing tariff.",
            "labels": ["rating", "data"],
        },
    ]


@pytest.fixture
def sample_conflicts() -> list[dict]:
    return [
        {
            "plan": "NMB_MAX_699",
            "config": 699.0,
            "observed": 749.0,
            "source_config": "config:plan[id=1]",
            "source_observed": "billed:invoice_line n=50",
        }
    ]


@pytest.fixture
def kb(sample_rules, sample_findings, sample_tickets, sample_conflicts) -> KnowledgeBase:
    return KnowledgeBase(
        rules=sample_rules,
        findings=sample_findings,
        tickets=sample_tickets,
        conflicts=sample_conflicts,
    )


# --------------------------------------------------------------------------- #
# Unit tests
# --------------------------------------------------------------------------- #


def test_findings_to_csv_header_and_rows(sample_findings):
    csv_str = findings_to_csv(sample_findings)
    reader = csv.reader(io.StringIO(csv_str))
    rows = list(reader)
    assert rows[0] == ["id", "check", "customer_id", "period", "impact", "money", "table", "record_ids", "description"]
    assert len(rows) == 4  # header + 3 findings
    assert rows[1][1] == "expired_discount"
    assert rows[1][7] == "r1;r2"


def test_findings_to_pdf_bytes(sample_findings):
    totals = {"count": 3, "found_total": 2000.0, "latest_period": "2024-01", "month_total": 2000.0}
    pdf_bytes = findings_to_pdf(sample_findings, totals, "Acme Corp")
    assert pdf_bytes.startswith(b"%PDF")


def test_classify_plan_id(kb):
    topic, subject = classify("document plan NMB_MAX_699", known_plans=["NMB_MAX_699", "NMB_MAX_999"])
    assert topic == "plan"
    assert subject == "NMB_MAX_699"


def test_classify_discount(kb):
    topic, subject = classify("show discount DISC10 details", known_plans=["NMB_MAX_699"])
    assert topic == "discount"
    assert subject is None


def test_classify_kt(kb):
    topic, subject = classify("KT doc for invoicing flow", known_plans=["NMB_MAX_699"])
    assert topic == "kt"
    assert subject is None


def test_classify_invoicing(kb):
    topic, subject = classify("explain invoicing flow", known_plans=["NMB_MAX_699"])
    assert topic == "invoicing"
    assert subject is None


def test_classify_changes(kb):
    topic, subject = classify("what changed recently", known_plans=["NMB_MAX_699"])
    assert topic == "changes"
    assert subject is None


def test_classify_leaks(kb):
    topic, subject = classify("show all revenue leaks", known_plans=["NMB_MAX_699"])
    assert topic == "leaks"
    assert subject is None


def test_classify_overview_fallback(kb):
    topic, subject = classify("hello world", known_plans=["NMB_MAX_699"])
    assert topic == "overview"
    assert subject is None


def test_generate_doc_all_topics_levels(kb):
    topics = ["plan", "discount", "invoicing", "leaks", "changes", "kt", "overview"]
    levels = ["exec", "analyst", "engineer"]
    for topic in topics:
        for level in levels:
            request_map = {
                "plan": "document plan NMB_MAX_699",
                "discount": "discount DISC10",
                "invoicing": "invoicing flow",
                "leaks": "show leaks",
                "changes": "changes history",
                "kt": "KT doc",
                "overview": "overview",
            }
            doc = generate_doc(request_map[topic], level, kb)
            assert isinstance(doc, Doc)
            assert doc.level == level
            assert len(doc.sections) > 0
            for section in doc.sections:
                for fact in section.facts:
                    assert fact.citations or fact.confidence == "needs confirmation"


def test_low_confidence_rule_needs_confirmation(kb):
    doc = generate_doc("document plan NMB_MAX_699", "analyst", kb)
    for section in doc.sections:
        for fact in section.facts:
            if "VOICE" in fact.text and "usage rate" in fact.text:
                assert fact.confidence == "needs confirmation"


def test_exec_level_summary_and_limit(kb):
    doc = generate_doc("show leaks", "exec", kb)
    summary_section = next((s for s in doc.sections if s.heading == "Summary"), None)
    assert summary_section is not None
    assert len(summary_section.facts) <= 3
    for section in doc.sections:
        if section.heading != "Summary":
            assert len(section.facts) <= 5


def test_analyst_level_limit(kb):
    doc = generate_doc("show leaks", "analyst", kb)
    for section in doc.sections:
        assert len(section.facts) <= 25


def test_engineer_has_data_sources(kb):
    doc = generate_doc("show leaks", "engineer", kb)
    data_sources_section = next((s for s in doc.sections if s.heading == "Data Sources"), None)
    assert data_sources_section is not None
    assert len(data_sources_section.facts) > 0


def test_to_markdown_footnotes_and_needs_confirmation(kb):
    doc = generate_doc("document plan NMB_MAX_699", "analyst", kb)
    md = to_markdown(doc)
    assert "## Sources" in md
    assert "[^1]" in md
    assert "(needs confirmation)" in md


def test_to_pdf_bytes(kb):
    doc = generate_doc("overview", "analyst", kb)
    pdf_bytes = to_pdf(doc)
    assert pdf_bytes.startswith(b"%PDF")


def test_to_confluence_storage_contains_draft_and_escaping(kb):
    # Use a request containing characters that need escaping
    special_request = "overview <b>&"
    doc = generate_doc(special_request, "analyst", kb)
    xml = to_confluence_storage(doc)
    assert "DRAFT generated by RevenueLens" in xml
    assert "<h1>" in xml
    assert "<h2>" in xml
    assert "<ul>" in xml
    assert "<li>" in xml
    # Verify proper escaping of the special request text
    escaped = re.escape("&lt;b&gt;")
    assert re.search(escaped, xml)
    assert "<b>" not in xml


def test_write_confluence_draft_creates_file(tmp_path, kb):
    doc = generate_doc("overview", "analyst", kb)
    file_path = write_confluence_draft(doc, tmp_path)
    assert file_path.exists()
    content = file_path.read_text()
    assert "DRAFT generated by RevenueLens" in content
    assert file_path.name.endswith(".confluence.xml")


def test_doc_to_dict_serializable(kb):
    doc = generate_doc("overview", "analyst", kb)
    d = doc_to_dict(doc)
    assert d["title"] == doc.title
    assert d["level"] == doc.level
    assert len(d["sections"]) == len(doc.sections)


def test_invalid_level_raises(kb):
    with pytest.raises(ValueError):
        generate_doc("overview", "invalid", kb)


# --------------------------------------------------------------------------- #
# Integration tests (require DB)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module", autouse=True)
def set_fake_llm():
    os.environ["RL_LLM"] = "fake"


@pytest.fixture(scope="module")
def db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def sim_loaded(db_url):
    from legacy_sim.__main__ import main as sim_main

    sim_main(["load", "--database-url", db_url])
    os.environ["LEGACY_DATABASE_URL"] = db_url
    from app.dashboard import reset_cache

    reset_cache()


@pytest.fixture(scope="module")
def client(sim_loaded, request):
    request.getfixturevalue("seeded")
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> None:
    r = client.post(
        "/login",
        data={"email": "admin@acme.test", "password": "s3cret-pass"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.cookies.get("rl_token")


def test_reports_csv_requires_auth(client):
    r = client.get("/api/reports/findings.csv")
    assert r.status_code == 401


def test_reports_csv_with_auth(client):
    _login(client)
    r = client.get("/api/reports/findings.csv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    content = r.text
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0] == ["id", "check", "customer_id", "period", "impact", "money", "table", "record_ids", "description"]
    assert len(rows) > 1


def test_reports_pdf_with_auth(client):
    _login(client)
    r = client.get("/api/reports/findings.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_docs_post_plan_engineer(client):
    _login(client)
    r = client.post("/api/docs", json={"request": "document plan NMB_MAX_699", "level": "engineer"})
    assert r.status_code == 200
    data = r.json()
    assert "sections" in data
    assert "markdown" in data
    assert len(data["sections"]) > 0
    assert "## Sources" in data["markdown"]


def test_docs_export_formats(client, tmp_path, monkeypatch):
    _login(client)
    monkeypatch.setenv("RL_DRAFTS_DIR", str(tmp_path))

    r = client.post("/api/docs", json={"request": "overview", "level": "analyst"})
    assert r.status_code == 200

    r = client.get("/api/docs/export?request=overview&level=analyst&format=md")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "## Sources" in r.text

    r = client.get("/api/docs/export?request=overview&level=analyst&format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")

    r = client.get("/api/docs/export?request=overview&level=analyst&format=confluence")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/xml"
    assert "X-Draft-Path" in r.headers
    assert "DRAFT generated by RevenueLens" in r.text

    r = client.get("/api/docs/export?request=overview&level=analyst&format=bad")
    assert r.status_code == 422


def test_docs_page_with_request(client):
    _login(client)
    r = client.get("/docs?request=KT+doc+for+invoicing+flow&level=exec")
    assert r.status_code == 200
    assert "needs-confirmation" in r.text or "Sources" in r.text


def test_reports_page(client):
    _login(client)
    r = client.get("/reports")
    assert r.status_code == 200
    assert "Reports" in r.text
    assert "Download CSV" in r.text
    assert "Download PDF" in r.text
