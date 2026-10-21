"""Evaluation module for RevenueLens step 4."""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

from app.adapters.postgres_readonly import ReadOnlyAdapter
from app.discovery import discover
from app.mapping import map_schema
from app.reconcile import CHECKS, Finding, run_checks

logger = logging.getLogger(__name__)


def load_ground_truth(path: str) -> list[dict[str, Any]]:
    """Load ground truth from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def score(
    findings: list[Finding],
    ground_truth: list[dict[str, Any]],
    checks: tuple[str, ...] = tuple(CHECKS.keys()),
) -> dict[str, Any]:
    """Score findings against ground truth."""
    # Build truth sets per check
    truth_by_check: dict[str, set[str]] = {check: set() for check in checks}
    for entry in ground_truth:
        gtype = entry.get("type", "")
        if gtype not in checks:
            continue
        record_ids = entry.get("record_ids", [])
        if isinstance(record_ids, list):
            for rid in record_ids:
                truth_by_check[gtype].add(str(rid))

    # Build found sets per check
    found_by_check: dict[str, set[str]] = {check: set() for check in checks}
    for finding in findings:
        if finding.check not in checks:
            continue
        for rid in finding.record_ids:
            found_by_check[finding.check].add(str(rid))

    per_check: dict[str, dict[str, Any]] = {}
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for check_name in checks:
        truth = truth_by_check[check_name]
        found = found_by_check[check_name]

        tp = len(truth & found)
        fp = len(found - truth)
        fn = len(truth - found)

        total_tp += tp
        total_fp += fp
        total_fn += fn

        if len(found) == 0:
            precision = 1.0 if len(truth) == 0 else 0.0
        else:
            precision = tp / len(found) if len(found) > 0 else 0.0

        if len(truth) == 0:
            recall = 1.0
        else:
            recall = tp / len(truth) if len(truth) > 0 else 0.0

        per_check[check_name] = {
            "found": len(found),
            "expected": len(truth),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }

    # Overall micro-averaged
    if total_tp + total_fp == 0:
        overall_precision = 1.0 if total_tp + total_fn == 0 else 0.0
    else:
        overall_precision = total_tp / (total_tp + total_fp)

    if total_tp + total_fn == 0:
        overall_recall = 1.0
    else:
        overall_recall = total_tp / (total_tp + total_fn)

    if overall_precision + overall_recall == 0:
        overall_f1 = 0.0
    else:
        overall_f1 = 2 * overall_precision * overall_recall / (overall_precision + overall_recall)

    return {
        "per_check": per_check,
        "overall": {
            "precision": round(overall_precision, 4),
            "recall": round(overall_recall, 4),
            "f1": round(overall_f1, 4),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Main entry point for evaluation."""
    parser = argparse.ArgumentParser(description="Evaluate RevenueLens reconciliation")
    parser.add_argument("--dsn", default=os.getenv("LEGACY_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--schema", default="nimbus")
    parser.add_argument("--ground-truth", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    if not args.dsn:
        logger.error("No DSN provided. Set LEGACY_DATABASE_URL or DATABASE_URL, or pass --dsn")
        return 1

    # Load ground truth
    if args.ground_truth:
        ground_truth = load_ground_truth(args.ground_truth)
    else:
        # Generate in-process
        try:
            from legacy_sim.generator import generate

            ground_truth = generate(seed=42, n_customers=500).ground_truth
        except ImportError as e:
            logger.error("Cannot generate ground truth: %s", e)
            return 1

    # Run checks
    with ReadOnlyAdapter(args.dsn, args.schema) as adapter:
        mapping = map_schema(discover(adapter))
        findings = run_checks(adapter, mapping)

    # Score
    results = score(findings, ground_truth)

    # Print table
    print(f"{'check':<30} {'found':>6} {'expected':>8} {'precision':>10} {'recall':>10}")
    print("-" * 70)
    for check_name, stats in results["per_check"].items():
        print(
            f"{check_name:<30} {stats['found']:>6} {stats['expected']:>8} "
            f"{stats['precision']:>10.4f} {stats['recall']:>10.4f}"
        )
    print("-" * 70)
    overall = results["overall"]
    print(
        f"{'OVERALL':<30} {'':>6} {'':>8} "
        f"{overall['precision']:>10.4f} {overall['recall']:>10.4f} "
        f"(f1={overall['f1']:.4f})"
    )

    # Write output if requested
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
