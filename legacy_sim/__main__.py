"""Command‑line interface for the legacy simulation package.

The CLI provides three sub‑commands:

* ``generate`` – generate a deterministic dataset and write CSV files,
  ground‑truth JSON, tickets JSON and markdown pages.
* ``load`` – create the ``nimbus`` schema in a PostgreSQL database and bulk‑load
  the generated data.
* ``summary`` – print a quick overview of the generated dataset (row counts and
  total impact per leak type).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg import Connection, sql

from .generator import Dataset, generate, to_ground_truth_json
from .oracle import find_leaks


def _write_csv(table_name: str, rows: list[dict[str, Any]], out_dir: Path) -> None:
    """Write a CSV file for *table_name* with a header matching column order."""
    if not rows:
        return
    out_path = out_dir / f"{table_name.lower()}.csv"
    fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Convert non‑primitive types to JSON‑serialisable primitives
            serialised = {
                k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()
            }
            writer.writerow(serialised)


def _execute_schema(conn: Connection, schema_path: Path) -> None:
    with schema_path.open("r", encoding="utf-8") as f:
        sql_text = f.read()
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()


def _copy_table(
    conn: Connection, table_name: str, rows: list[dict[str, Any]]
) -> int:
    """Copy *rows* into the given *table_name* using PostgreSQL COPY."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    # Build a comma‑separated list of identifiers, lower‑casing column names.
    col_sql = sql.SQL(", ").join(sql.Identifier(c.lower()) for c in cols)
    # Table identifier must be lower‑cased to match unquoted PostgreSQL names.
    tbl_sql = sql.Identifier("nimbus", table_name.lower())
    query = sql.SQL("COPY {tbl} ({cols}) FROM STDIN").format(
        tbl=tbl_sql, cols=col_sql
    )
    with conn.cursor() as cur:
        with cur.copy(query) as copy:
            # Write data rows
            for row in rows:
                copy.write_row([row[c] for c in cols])
        # The copy protocol does not set rowcount; we know how many rows we wrote.
        count = len(rows)
    conn.commit()
    return count


def cmd_generate(args: argparse.Namespace) -> int:
    ds: Dataset = generate(seed=args.seed, n_customers=args.customers, randomize=getattr(args, "randomize", False))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write CSVs
    for tbl, rows in ds.tables.items():
        _write_csv(tbl, rows, out_dir)

    # Ground‑truth and tickets
    (out_dir / "ground_truth.json").write_text(to_ground_truth_json(ds), encoding="utf-8")
    (out_dir / "tickets.json").write_text(json.dumps(ds.tickets, indent=2), encoding="utf-8")

    # Markdown pages
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for name, content in ds.pages.items():
        (pages_dir / f"{name}.md").write_text(content, encoding="utf-8")

    print(f"Generated dataset with {len(ds.tables)} tables under {out_dir}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    ds: Dataset = generate(seed=args.seed, n_customers=args.customers, randomize=getattr(args, "randomize", False))
    db_url = args.database_url or os.getenv("LEGACY_DATABASE_URL") or os.getenv(
        "DATABASE_URL"
    )
    if not db_url:
        print("Database URL not provided.", file=sys.stderr)
        return 1

    schema_path = Path(__file__).with_name("schema.sql")
    with Connection.connect(db_url) as conn:
        _execute_schema(conn, schema_path)

        order = [
            "CUST_MSTR",
            "RT_PLAN_CFG",
            "TRF_RATE_CFG",
            "DISC_CFG",
            "CONTRACT_TERMS",
            "SUBSCR_MSTR",
            "SUBSCR_DISC",
            "RENEW_LOG",
            "USG_CDR",
            "RTD_EVT",
            "BILL_HDR",
            "BILL_DTL",
            "PYMT_TXN",
        ]
        for tbl in order:
            rows = ds.tables.get(tbl, [])
            count = _copy_table(conn, tbl, rows)
            print(f"Loaded {count} rows into nimbus.{tbl}")

    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    ds: Dataset = generate(seed=args.seed, n_customers=args.customers, randomize=getattr(args, "randomize", False))
    # Row counts
    for tbl, rows in ds.tables.items():
        print(f"{tbl}: {len(rows)} rows")
    # Leak summary
    leaks = find_leaks(ds)
    total_impact = Decimal(0)
    for lt, ids in leaks.items():
        # Impact is summed from the ground‑truth list
        impact = sum(
            (Decimal(str(item["impact_inr"])) for item in ds.ground_truth if item["type"] == lt),
            Decimal(0),
        )
        total_impact += impact
        print(f"{lt}: {len(ids)} leaks, impact {impact}")
    print(f"Overall impact: {total_impact}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legacy_sim")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    gen = subparsers.add_parser("generate", help="Generate synthetic data")
    gen.add_argument("--randomize", action="store_true", help="Randomise which leaks are planted")
    gen.add_argument("--seed", type=int, default=42, help="Random seed")
    gen.add_argument(
        "--customers", type=int, default=500, help="Number of customers to generate"
    )
    gen.add_argument(
        "--out", type=str, default="data/legacy_sim", help="Output directory"
    )
    gen.set_defaults(func=cmd_generate)

    load = subparsers.add_parser("load", help="Load data into PostgreSQL")
    load.add_argument("--randomize", action="store_true", help="Randomise which leaks are planted")
    load.add_argument("--seed", type=int, default=42)
    load.add_argument(
        "--customers", type=int, default=500, help="Number of customers to generate"
    )
    load.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection URL (overrides env vars)",
    )
    load.set_defaults(func=cmd_load)

    summ = subparsers.add_parser("summary", help="Print a quick summary")
    summ.add_argument("--randomize", action="store_true", help="Randomise which leaks are planted")
    summ.add_argument("--seed", type=int, default=42)
    summ.add_argument("--customers", type=int, default=500)
    summ.set_defaults(func=cmd_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
