"""Command-line entry point for discovering and reconciling a data source.

Usage::

    python -m app.sources_cli --csv DIR
    python -m app.sources_cli --postgres URL
    python -m app.sources_cli --csv DIR --knowledge KNOWLEDGE_DIR

Prints a JSON summary with per-check findings and optional knowledge-item count.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.adapters import open_source
from app.discovery import discover
from app.explain import match_tickets  # noqa: F401  (re-exported conceptually)
from app.knowledge import load_all
from app.mapping import map_schema
from app.reconcile import run_checks


def _build_adapter(args: argparse.Namespace) -> Any:
    if args.csv:
        return open_source("csv", args.csv, schema=args.schema)
    if args.postgres:
        return open_source("postgres", args.postgres, schema=args.schema)
    raise SystemExit("Either --csv or --postgres must be provided")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover and reconcile a RevenueLens data source.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Path to a directory of CSV exports")
    src.add_argument("--postgres", help="Postgres DSN / URL")
    parser.add_argument("--schema", default="nimbus", help="Schema name (default: nimbus)")
    parser.add_argument("--knowledge", help="Path to a knowledge export directory")
    args = parser.parse_args(argv)

    adapter = _build_adapter(args)
    try:
        tables = discover(adapter)
        schema = map_schema(adapter, tables)
        findings = run_checks(adapter, schema)

        per_check_counts: dict[str, int] = {}
        per_check_money: dict[str, float] = {}
        total_money = 0.0
        for finding in findings:
            per_check_counts[finding.check] = per_check_counts.get(finding.check, 0) + 1
            per_check_money[finding.check] = per_check_money.get(finding.check, 0.0) + finding.impact
            total_money += finding.impact

        summary: dict[str, Any] = {
            "tables": tables,
            "checks": {
                check: {
                    "records": count,
                    "money": per_check_money.get(check, 0.0),
                }
                for check, count in per_check_counts.items()
            },
            "total_money": total_money,
            "findings": len(findings),
        }

        if args.knowledge:
            items = load_all(args.knowledge)
            summary["knowledge_items"] = len(items)

        print(json.dumps(summary, indent=2, default=str))
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    sys.exit(main())
