from __future__ import annotations

import json
from typing import Any

from legacy_sim.generator import LEAK_TYPES

ANSWER_KEY_TYPES = LEAK_TYPES


def store_planted(conn, tenant_id: str, seed: int, ground_truth: list[dict]) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM planted_issue WHERE tenant_id = %s", (tenant_id,))
        cur.execute("DELETE FROM demo_run WHERE tenant_id = %s", (tenant_id,))
        cur.execute(
            "INSERT INTO demo_run (tenant_id, seed) VALUES (%s, %s)",
            (tenant_id, seed),
        )
        count = 0
        for entry in ground_truth:
            if entry["type"] not in ANSWER_KEY_TYPES:
                continue
            cur.execute(
                """
                INSERT INTO planted_issue (tenant_id, leak_id, check_name, table_name, record_ids, bill_prd, impact_inr, description, cust_no)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, leak_id) DO NOTHING
                """,
                (
                    tenant_id,
                    entry["leak_id"],
                    entry["type"],
                    entry["table"],
                    json.dumps([str(x) for x in entry["record_ids"]]),
                    entry["bill_prd"],
                    entry["impact_inr"],
                    entry["description"],
                    entry["cust_no"],
                ),
            )
            count += cur.rowcount
    return count


def get_seed(conn) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT seed FROM demo_run LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def list_planted(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT leak_id, check_name, table_name, record_ids, bill_prd, impact_inr, description, cust_no
            FROM planted_issue
            ORDER BY check_name, leak_id
            """
        )
        rows = cur.fetchall()
    result = []
    for r in rows:
        record_ids = r[3]
        if isinstance(record_ids, str):
            record_ids = json.loads(record_ids)
        result.append(
            {
                "leak_id": r[0],
                "check_name": r[1],
                "table_name": r[2],
                "record_ids": record_ids,
                "bill_prd": r[4],
                "impact_inr": float(r[5]) if r[5] is not None else 0.0,
                "description": r[6],
                "cust_no": r[7],
            }
        )
    return result


def compare(planted: list[dict], findings: list[Any]) -> dict:
    planted_by_check: dict[str, list[dict]] = {}
    for p in planted:
        planted_by_check.setdefault(p["check_name"], []).append(p)

    finding_matched = [False] * len(findings)
    planted_matched = [False] * len(planted)
    planted_finding_index: list[int | None] = [None] * len(planted)

    for i, p in enumerate(planted):
        p_ids = {str(x) for x in p["record_ids"]}
        for j, f in enumerate(findings):
            if f.check == p["check_name"] and p_ids & {str(x) for x in f.record_ids}:
                finding_matched[j] = True
                if not planted_matched[i]:
                    planted_matched[i] = True
                    planted_finding_index[i] = j

    false_positives = []
    for j, f in enumerate(findings):
        if not finding_matched[j]:
            false_positives.append(
                {
                    "index": j,
                    "check": f.check,
                    "customer_id": f.customer_id,
                    "record_ids": f.record_ids,
                    "impact": f.impact,
                    "description": f.description,
                }
            )

    issues = []
    for i, p in enumerate(planted):
        issues.append(
            {
                **p,
                "detected": planted_matched[i],
                "finding_index": planted_finding_index[i],
            }
        )

    per_check: dict[str, dict] = {}
    for check in ANSWER_KEY_TYPES:
        check_planted = [p for p in planted if p["check_name"] == check]
        check_detected = sum(1 for p in check_planted if p["leak_id"] in [x["leak_id"] for x in issues if x["detected"]])
        check_fp = sum(1 for fp in false_positives if fp["check"] == check)
        per_check[check] = {
            "planted": len(check_planted),
            "detected": check_detected,
            "missed": len(check_planted) - check_detected,
            "false_positives": check_fp,
        }

    total_planted = len(planted)
    total_detected = sum(1 for x in issues if x["detected"])
    total_missed = total_planted - total_detected
    total_findings = len(findings)
    tp_findings = total_findings - len(false_positives)
    precision = round(tp_findings / total_findings, 4) if total_findings else 1.0
    recall = total_detected / total_planted if total_planted else 1.0

    return {
        "issues": issues,
        "false_positives": false_positives,
        "per_check": per_check,
        "planted": total_planted,
        "detected": total_detected,
        "missed": total_missed,
        "precision": precision,
        "recall": recall,
    }


def build_report(conn) -> dict:
    from app.dashboard import load_findings

    planted = list_planted(conn)
    findings = load_findings()
    report = compare(planted, findings)
    report["seed"] = get_seed(conn)
    return report
