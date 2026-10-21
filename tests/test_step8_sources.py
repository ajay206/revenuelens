"""Tests for Step 8 sources CLI, CSV adapter, and knowledge connectors."""

from __future__ import annotations

import os
import socket

import pytest

import legacy_sim.__main__ as legacy_main
import legacy_sim.generator as gen
from app.adapters import CsvExportAdapter
from app.discovery import discover
from app.evaluate import score
from app.explain import match_tickets
from app.knowledge import (
    AdoConnector,
    ConfluenceConnector,
    JiraConnector,
    as_tickets,
    load_all,
)
from app.mapping import map_schema
from app.reconcile import run_checks


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def csv_export_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    export_dir = tmp_path_factory.mktemp("csv_export")
    legacy_main.main(["generate", "--out", str(export_dir)])
    return str(export_dir)


@pytest.fixture(scope="module")
def tickets_path(csv_export_dir: str) -> str:
    return os.path.join(csv_export_dir, "tickets.json")


@pytest.fixture(scope="module")
def pages_dir(csv_export_dir: str) -> str:
    return os.path.join(csv_export_dir, "pages")


# --------------------------------------------------------------------------- #
# CsvExportAdapter tests
# --------------------------------------------------------------------------- #
def test_csv_adapter_lists_tables(csv_export_dir: str) -> None:
    with CsvExportAdapter(csv_export_dir) as adapter:
        tables = adapter.list_tables()
        assert "cust_mstr" in tables
        assert "usg_cdr" in tables
        assert "bill_hdr" in tables


def test_csv_adapter_row_count(csv_export_dir: str) -> None:
    with CsvExportAdapter(csv_export_dir) as adapter:
        assert adapter.row_count("cust_mstr") == 500


def test_csv_adapter_query_rejects_non_select(csv_export_dir: str) -> None:
    with CsvExportAdapter(csv_export_dir) as adapter, pytest.raises(ValueError):
        adapter.query("DELETE FROM nimbus.cust_mstr")


# --------------------------------------------------------------------------- #
# Knowledge connector tests
# --------------------------------------------------------------------------- #
def test_jira_connector_source_filter(tickets_path: str) -> None:
    connector = JiraConnector.from_export(tickets_path)
    items = connector.items()
    assert all(item.source == "jira" for item in items)


def test_ado_connector_source_filter(tickets_path: str) -> None:
    connector = AdoConnector.from_export(tickets_path)
    items = connector.items()
    assert all(item.source == "ado" for item in items)


def test_total_tickets_count(tickets_path: str) -> None:
    jira = JiraConnector.from_export(tickets_path).items()
    ado = AdoConnector.from_export(tickets_path).items()
    assert len(jira) + len(ado) == 12


def test_confluence_connector_page_count(pages_dir: str) -> None:
    connector = ConfluenceConnector.from_export(pages_dir)
    items = connector.items()
    assert len(items) >= 1
    assert items[0].title  # must have a non-empty title


def test_jira_search_finds_discount_ticket(tickets_path: str) -> None:
    connector = JiraConnector.from_export(tickets_path)
    results = connector.search("discount")
    keys = [item.key for item in results]
    assert "NIM-101" in keys


def test_as_tickets_shape(tickets_path: str) -> None:
    jira = JiraConnector.from_export(tickets_path)
    tickets = as_tickets(jira.items())
    for ticket in tickets:
        assert set(ticket.keys()) == {"key", "source", "title", "description", "labels", "created"}


def test_load_all_returns_items(csv_export_dir: str) -> None:
    items = load_all(csv_export_dir)
    assert len(items) > 0


# --------------------------------------------------------------------------- #
# Explain / match_tickets test
# --------------------------------------------------------------------------- #
def test_match_tickets_for_expired_discount(tickets_path: str) -> None:
    from app.reconcile import Finding  # local import to avoid circular dependency

    finding = Finding(
        check="expired_discount",
        record_ids=["rec-1"],
        table="bill_dtl",
        customer_id="cust-1",
        period="2025-11",
        impact=1.0,
        evidence={},
        description="Expired discount applied",
    )
    tickets = as_tickets(JiraConnector.from_export(tickets_path).items())
    matched = match_tickets(finding, tickets)
    assert isinstance(matched, list)


# --------------------------------------------------------------------------- #
# Reconcile / run_checks tests
# --------------------------------------------------------------------------- #
def test_run_checks_scores(csv_export_dir: str) -> None:
    ground_truth = gen.generate(seed=42, n_customers=500).ground_truth
    with CsvExportAdapter(csv_export_dir, schema="nimbus") as adapter:
        findings = run_checks(adapter, map_schema(discover(adapter)))
        result = score(findings, ground_truth)
        per_check = result["per_check"]
        for check in per_check:
            assert per_check[check]["precision"] == 1.0
            assert per_check[check]["recall"] == 1.0


# --------------------------------------------------------------------------- #
# Postgres parity test (skipped if DB unavailable)
# --------------------------------------------------------------------------- #
def _postgres_available(url: str) -> bool:
    try:
        host_part = url.split("@")[-1].split("/")[0].split(":")[0]
        port = int(url.split("@")[-1].split("/")[0].split(":")[1])
        socket.create_connection((host_part, port), timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def test_csv_matches_postgres_findings(csv_export_dir: str) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url or not _postgres_available(url):
        pytest.skip("DATABASE_URL not set or unreachable")

    legacy_main.main(["load", "--database-url", url])

    with CsvExportAdapter(csv_export_dir) as csv_adapter:
        csv_findings = run_checks(csv_adapter, map_schema(discover(csv_adapter)))

    from app.adapters.postgres_readonly import ReadOnlyAdapter
    with ReadOnlyAdapter(url, schema="nimbus") as pg_adapter:
        pg_findings = run_checks(pg_adapter, map_schema(discover(pg_adapter)))

    def findings_key(findings: list) -> set:
        return {(f.check, tuple(f.record_ids)) for f in findings}

    assert findings_key(csv_findings) == findings_key(pg_findings)
