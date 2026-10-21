from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from .config import get_settings
from .explain import Story
from .reconcile import Finding

# Deterministic plain-English fix descriptions per check
PROPOSED_ACTIONS: dict[str, str] = {
    "unrated_usage": "re-run rating for the listed usage records",
    "rated_not_invoiced": "add rated events to next invoice",
    "tariff_mismatch": "correct the rate in tariff config and re-bill the difference",
    "expired_discount": "end-date the discount and re-bill",
    "provisioned_not_billed": "create billing account and back-bill",
    "missed_renewal": "renew contract and bill missed months",
    "unmatched_payment": "link payment to its invoice",
    "duplicate_charge": "credit-note the duplicate line",
}


def leak_key(finding: Finding) -> str:
    """Generate a deterministic leak key: check_name:first_record_id"""
    first_record = finding.record_ids[0] if finding.record_ids else "none"
    return f"{finding.check}:{first_record}"


def _get_tenant_id() -> str:
    """Get tenant_id from settings."""
    return str(get_settings().company_id)


def draft_fix(conn: Connection, tenant_id: str, finding: Finding, story: Story, actor: str) -> dict[str, Any]:
    """
    Upsert a fix draft. Returns the draft row as dict.
    Only writes audit_log 'draft_created' when newly inserted.
    """
    lk = leak_key(finding)
    amount = round(abs(finding.impact), 2)
    title = story.title
    payload = {
        "record_ids": finding.record_ids,
        "table": finding.table,
        "citations": [{"type": c.type, "ref": c.ref} for c in story.citations],
    }
    proposed = PROPOSED_ACTIONS.get(finding.check, "review and apply appropriate correction")

    with conn.cursor(row_factory=dict_row) as cur:
        # Try to insert
        cur.execute(
            """
            INSERT INTO fix_draft (tenant_id, leak_key, check_name, customer_id, amount, title,
                                   proposed_action, payload, status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s)
            ON CONFLICT (tenant_id, leak_key) DO NOTHING
            RETURNING id
            """,
            (tenant_id, lk, finding.check, finding.customer_id, amount, title,
             proposed, json.dumps(payload), actor),
        )
        row = cur.fetchone()
        if row:
            # Newly created - log audit
            draft_id = row["id"]
            _log_audit(cur, tenant_id, actor, "draft_created", str(draft_id),
                       {"leak_key": lk, "check": finding.check, "amount": str(amount)})
        else:
            # Already exists - fetch it
            cur.execute(
                "SELECT id FROM fix_draft WHERE tenant_id = %s AND leak_key = %s",
                (tenant_id, lk),
            )
            row = cur.fetchone()
            draft_id = row["id"]

        # Return full draft
        cur.execute("SELECT * FROM fix_draft WHERE id = %s", (draft_id,))
        return cur.fetchone()


def list_fixes(conn: Connection, status: str | None = None) -> list[dict[str, Any]]:
    """List fix drafts, optionally filtered by status."""
    with conn.cursor(row_factory=dict_row) as cur:
        if status:
            cur.execute(
                "SELECT * FROM fix_draft WHERE tenant_id = %s AND status = %s ORDER BY created_at DESC",
                (_get_tenant_id(), status),
            )
        else:
            cur.execute(
                "SELECT * FROM fix_draft WHERE tenant_id = %s ORDER BY created_at DESC",
                (_get_tenant_id(),),
            )
        return cur.fetchall()


def get_fix(conn: Connection, fix_id: UUID) -> dict[str, Any] | None:
    """Get a single fix draft by ID."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM fix_draft WHERE id = %s", (str(fix_id),))
        return cur.fetchone()


def decide_fix(conn: Connection, fix_id: UUID, actor: str, approve: bool, note: str) -> dict[str, Any]:
    """
    Approve or reject a fix draft. Only allowed from 'draft' status.
    Raises ValueError if not in draft status.
    """
    new_status = "approved" if approve else "rejected"
    action = "fix_approved" if approve else "fix_rejected"

    with conn.cursor(row_factory=dict_row) as cur:
        # Check current status
        cur.execute("SELECT status, leak_key FROM fix_draft WHERE id = %s", (str(fix_id),))
        row = cur.fetchone()
        if not row:
            raise ValueError("Fix draft not found")
        if row["status"] != "draft":
            raise ValueError(f"Fix draft is not in 'draft' status (current: {row['status']})")

        # Update
        cur.execute(
            """
            UPDATE fix_draft
            SET status = %s, decided_by = %s, decided_at = now(), decision_note = %s
            WHERE id = %s
            RETURNING *
            """,
            (new_status, actor, note, str(fix_id)),
        )
        updated = cur.fetchone()

        # Audit log
        _log_audit(cur, _get_tenant_id(), actor, action, str(fix_id),
                   {"previous_status": "draft", "new_status": new_status, "note": note})

        return updated


def list_audit(conn: Connection, limit: int = 200) -> list[dict[str, Any]]:
    """List audit log entries, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM audit_log WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
            (_get_tenant_id(), limit),
        )
        return cur.fetchall()


def log(conn: Connection, tenant_id: str, actor: str, action: str,
        target: str | None, details: dict[str, Any] | None) -> None:
    """Convenience function to write an audit log entry."""
    with conn.cursor() as cur:
        _log_audit(cur, tenant_id, actor, action, target, details)


def _log_audit(cur, tenant_id: str, actor: str, action: str,
               target: str | None, details: dict[str, Any] | None) -> None:
    """Internal helper to write audit log using existing cursor."""
    cur.execute(
        """
        INSERT INTO audit_log (tenant_id, actor, action, target, details)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (tenant_id, actor, action, target, json.dumps(details) if details else None),
    )
