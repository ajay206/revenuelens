"""Tests for RevenueLens step 4 reconciliation."""

from __future__ import annotations

import os

import psycopg
import pytest

from app.adapters.postgres_readonly import ReadOnlyAdapter
from app.discovery import discover
from app.evaluate import score
from app.mapping import map_schema
from app.reconcile import CHECKS, Finding, run_checks, summarize


@pytest.fixture(scope="module")
def dsn() -> str:
    """Database connection string fixture."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(url) as conn:
            conn.close()
    except Exception:  # noqa: BLE001
        pytest.skip("Database not available")
    # Load test data
    from legacy_sim.__main__ import main as sim_main

    sim_main(["load", "--database-url", url])
    return url


@pytest.fixture(scope="module")
def findings(dsn: str) -> list[Finding]:
    """Run all checks and return findings."""
    with ReadOnlyAdapter(dsn, "nimbus") as adapter:
        mapping = map_schema(discover(adapter))
        return run_checks(adapter, mapping)


@pytest.fixture(scope="module")
def ground_truth() -> list[dict]:
    """Generate ground truth for testing."""
    from legacy_sim.generator import generate

    return generate(seed=42, n_customers=500).ground_truth


def test_all_checks_present_in_summary(findings: list[Finding]) -> None:
    """All 8 check names appear in summarize output."""
    summary = summarize(findings)
    for check_name in CHECKS:
        assert check_name in summary, f"Check {check_name} missing from summary"


def test_overall_recall_precision(findings: list[Finding], ground_truth: list[dict]) -> None:
    """Overall recall >= 0.9 and precision >= 0.8."""
    results = score(findings, ground_truth)
    overall = results["overall"]
    assert overall["recall"] >= 0.9, f"Overall recall {overall['recall']} < 0.9"
    assert overall["precision"] >= 0.8, f"Overall precision {overall['precision']} < 0.8"


def test_per_check_recall(findings: list[Finding], ground_truth: list[dict]) -> None:
    """Each check recall >= 0.75."""
    results = score(findings, ground_truth)
    for check_name, stats in results["per_check"].items():
        assert stats["recall"] >= 0.75, f"Check {check_name} recall {stats['recall']} < 0.75"


def test_duplicate_charge_impacts_negative(findings: list[Finding]) -> None:
    """Duplicate charge findings have negative impact."""
    for finding in findings:
        if finding.check == "duplicate_charge":
            assert finding.impact < 0, (
                f"Duplicate charge {finding.record_ids} has positive impact {finding.impact}"
            )


def test_score_perfect_match() -> None:
    """Score function with perfect match."""
    findings = [
        Finding(
            check="unrated_usage",
            record_ids=["u1", "u2"],
            table="usage",
            customer_id="c1",
            period="202401",
            impact=100.0,
            evidence={},
            description="test",
        )
    ]
    ground_truth = [
        {"type": "unrated_usage", "record_ids": ["u1", "u2"], "impact_inr": 100.0}
    ]
    results = score(findings, ground_truth, checks=("unrated_usage",))
    assert results["per_check"]["unrated_usage"]["precision"] == 1.0
    assert results["per_check"]["unrated_usage"]["recall"] == 1.0
    assert results["overall"]["precision"] == 1.0
    assert results["overall"]["recall"] == 1.0


def test_score_one_false_positive() -> None:
    """Score function with one false positive."""
    findings = [
        Finding(
            check="unrated_usage",
            record_ids=["u1", "u2"],
            table="usage",
            customer_id="c1",
            period="202401",
            impact=100.0,
            evidence={},
            description="test",
        ),
        Finding(
            check="unrated_usage",
            record_ids=["u3"],
            table="usage",
            customer_id="c1",
            period="202401",
            impact=50.0,
            evidence={},
            description="test",
        ),
    ]
    ground_truth = [
        {"type": "unrated_usage", "record_ids": ["u1", "u2"], "impact_inr": 100.0}
    ]
    results = score(findings, ground_truth, checks=("unrated_usage",))
    # Found 3, expected 2, TP=2, FP=1, FN=0
    assert results["per_check"]["unrated_usage"]["precision"] == pytest.approx(2 / 3, abs=1e-3)
    assert results["per_check"]["unrated_usage"]["recall"] == 1.0
