import argparse
import json
import os
import random
from pathlib import Path
from typing import Any

from app.answer_key import compare, list_planted, store_planted
from app.config import get_settings
from app.dashboard import load_findings, load_stories, reset_cache
from app.db import company_conn
from app.fixes import decide_fix, draft_fix, log
from app.reconcile import Finding
from legacy_sim.generator import generate


def _print(msg: str) -> None:
    """Simple wrapper for printing to stdout."""
    print(msg)


def _get_demo_seed(conn) -> int | None:
    """Return the existing demo seed for the current tenant, or ``None``."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seed FROM demo_run WHERE tenant_id = %s",
                (str(get_settings().company_id),),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:  # noqa: BLE001
        # Table might not exist yet
        return None


def _determine_seed(conn) -> int:
    """Determine which seed to use for the demo.

    Preference order:
    1. Existing seed in ``demo_run`` for the tenant.
    2. ``DEMO_SEED`` environment variable.
    3. Randomly generated seed.
    """
    existing = _get_demo_seed(conn)
    if existing is not None:
        return existing

    env_seed = os.getenv("DEMO_SEED")
    if env_seed and env_seed.isdigit():
        return int(env_seed)

    return random.SystemRandom().randint(1, 999_999)


def _write_ground_truth(gt: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2, ensure_ascii=False)


def _draft_fixes_if_needed(
    conn,
    tenant_id: str,
    findings: list[Finding],
    stories: list[Any],
) -> None:
    """Create draft fixes for up to eight findings if none exist yet."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM fix_draft WHERE tenant_id = %s", (tenant_id,)
        )
        count = cur.fetchone()[0]

    if count > 0:
        return

    max_drafts = min(8, len(findings))
    for i in range(max_drafts):
        draft_fix(conn, tenant_id, findings[i], stories[i], "ra.analyst@nimbus.example")


def _process_approvals(conn, tenant_id: str) -> None:
    """Approve/reject the first three drafts if they exist."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM fix_draft WHERE tenant_id = %s ORDER BY amount DESC, id", (tenant_id,)
        )
        draft_ids = [row[0] for row in cur.fetchall()]

    if not draft_ids:
        return

    if len(draft_ids) >= 1:
        decide_fix(conn, draft_ids[0], "finance.lead@nimbus.example", True,
                    "Verified against replayed bill; approve credit/re-bill.")
    if len(draft_ids) >= 2:
        decide_fix(conn, draft_ids[1], "finance.lead@nimbus.example", True,
                    "Verified against replayed bill; approve credit/re-bill.")
    if len(draft_ids) >= 3:
        decide_fix(conn, draft_ids[2], "finance.lead@nimbus.example", False,
                    "Customer already credited manually in CRM; not a leak.")


def _log_audit_entries(conn, tenant_id: str, seed: int, planted_cnt: int,
                       findings_cnt: int) -> None:
    log(
        conn,
        tenant_id,
        "system",
        "demo_seeded",
        f"seed:{seed}",
        {"planted": planted_cnt},
    )
    log(
        conn,
        tenant_id,
        "ra.analyst@nimbus.example",
        "report_generated",
        "findings.pdf",
        {"format": "pdf", "findings": findings_cnt},
    )
    log(
        conn,
        tenant_id,
        "ra.analyst@nimbus.example",
        "report_generated",
        "findings.csv",
        {"format": "csv", "findings": findings_cnt},
    )


def _run_demo(seed: int, out_path: Path) -> None:
    """Run the full demo pipeline for a given seed."""
    # 1️⃣ Generate data and store answer key
    ds = generate(seed=seed, randomize=True)
    _write_ground_truth(ds.ground_truth, out_path)

    with company_conn() as conn:
        tenant_id = str(get_settings().company_id)
        planted_cnt = store_planted(conn, tenant_id, seed, ds.ground_truth)

    # 2️⃣ Reset dashboard cache and load detections
    reset_cache()
    findings = load_findings()
    stories = load_stories()
    _print(f"Detected {len(findings)} findings")

    # 3️⃣ Draft fixes (idempotent) and process approvals
    with company_conn() as conn:
        tenant_id = str(get_settings().company_id)
        _draft_fixes_if_needed(conn, tenant_id, findings, stories)
        _process_approvals(conn, tenant_id)

    # 4️⃣ Log audit actions
    with company_conn() as conn:
        tenant_id = str(get_settings().company_id)
        _log_audit_entries(conn, tenant_id, seed, planted_cnt, len(findings))

    # 5️⃣ Grading summary
    planted = []
    with company_conn() as conn:
        planted = list_planted(conn)
    report = compare(planted, findings)
    _print("=== Grading Summary ===")
    _print(f"Seed: {seed}")
    _print(f"Planted: {report['planted']}")
    _print(f"Detected: {report['detected']}")
    _print(f"Missed: {report['missed']}")
    _print(f"Precision: {report['precision']:.4f}")
    _print(f"Recall: {report['recall']:.4f}")


def _seed_subcommand(args: argparse.Namespace) -> None:
    with company_conn() as conn:
        seed = _determine_seed(conn)
    _print(str(seed))


def _run_subcommand(args: argparse.Namespace) -> None:
    out_path = Path(args.ground_truth_out)
    _run_demo(args.seed, out_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.demo_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="Print the demo seed")
    seed_parser.set_defaults(func=_seed_subcommand)

    run_parser = subparsers.add_parser("run", help="Run the demo pipeline")
    run_parser.add_argument("--seed", type=int, required=True, help="Demo seed")
    run_parser.add_argument(
        "--ground-truth-out",
        default="/tmp/ground_truth.json",
        help="Path to write generated ground‑truth JSON",
    )
    run_parser.set_defaults(func=_run_subcommand)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
