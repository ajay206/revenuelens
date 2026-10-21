# Step 7: Fix Drafts, Approval Queue & Audit Trail

## Overview

RevenueLens is **read-only** toward the legacy billing system. We never write directly to it. Instead, every corrective action becomes a **Fix Draft** — a structured record that a human reviews and either approves or rejects. The approval itself is just a decision record; it does not mutate the legacy system. An external process (or human operator) will later act on approved fixes.

This step introduces three core concepts:
1. **Fix Drafts** — proposed corrections derived from leak findings
2. **Approval Queue** — a UI + API for reviewing and deciding on drafts
3. **Audit Trail** — an immutable log of every significant action

---

## Database Schema

### `fix_draft` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `uuid` | Primary key, `gen_random_uuid()` |
| `tenant_id` | `uuid` | FK → `tenant(id)`, RLS scope |
| `leak_key` | `text` | Deterministic key: `check_name:first_record_id` (unique per tenant) |
| `check_name` | `text` | Which check produced this leak |
| `customer_id` | `text` | Customer identifier |
| `amount` | `numeric(18,2)` | Absolute impact, rounded to 2 decimals |
| `title` | `text` | Human-readable title from the story |
| `proposed_action` | `text` | Plain-English fix description (deterministic per check) |
| `payload` | `jsonb` | Structured context: `record_ids`, `table`, `citations` |
| `status` | `text` | `draft` \| `approved` \| `rejected` (default `draft`) |
| `created_by` | `text` | Email of user who created the draft |
| `decided_by` | `text` | Email of user who approved/rejected |
| `decided_at` | `timestamptz` | When the decision was made |
| `decision_note` | `text` | Optional note from the decider |
| `created_at` | `timestamptz` | `now()` |

**Constraints:**
- `UNIQUE (tenant_id, leak_key)` — prevents duplicate drafts for the same leak
- `CHECK (status IN ('draft','approved','rejected'))`

**Row Level Security:**
- `ENABLE ROW LEVEL SECURITY`
- `FORCE ROW LEVEL SECURITY`
- Policy: `USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)` with same `WITH CHECK`

### `audit_log` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `bigserial` | Primary key |
| `tenant_id` | `uuid` | FK → `tenant(id)`, RLS scope |
| `actor` | `text` | Email of the user who performed the action |
| `action` | `text` | Action type (see below) |
| `target` | `text` | Optional reference (e.g., fix draft ID) |
| `details` | `jsonb` | Structured details |
| `created_at` | `timestamptz` | `now()` |

**Row Level Security:** Same pattern as `fix_draft`.

**Append-Only for App User:**
- `GRANT SELECT, INSERT` only (no UPDATE, DELETE)
- `REVOKE UPDATE, DELETE ON audit_log FROM revenuelens_app`

This ensures the audit trail cannot be tampered with by the application.

---

## Deterministic Proposed Actions

Each check type maps to a fixed plain-English description:

| Check | Proposed Action |
|-------|-----------------|
| `unrated_usage` | re-run rating for the listed usage records |
| `rated_not_invoiced` | add rated events to next invoice |
| `tariff_mismatch` | correct the rate in tariff config and re-bill the difference |
| `expired_discount` | end-date the discount and re-bill |
| `provisioned_not_billed` | create billing account and back-bill |
| `missed_renewal` | renew contract and bill missed months |
| `unmatched_payment` | link payment to its invoice |
| `duplicate_charge` | credit-note the duplicate line |

This mapping lives in `app/fixes.py` as `PROPOSED_ACTIONS`. It is **deterministic** — no LLM involved.

---

## Leak Key

The `leak_key` is the deduplication anchor:
```
leak_key = f"{finding.check}:{finding.record_ids[0]}"
```

Example: `unrated_usage:usr_12345`

Two findings with the same check and same first record ID are considered the same leak. The `UNIQUE (tenant_id, leak_key)` constraint enforces this at the database level.

---

## Core Functions (`app/fixes.py`)

### `draft_fix(conn, tenant_id, finding, story, actor) → dict`
- Upserts a fix draft using `ON CONFLICT (tenant_id, leak_key) DO NOTHING`
- If newly inserted: writes `audit_log` action `draft_created`
- If already exists: returns existing draft (no new audit entry)
- Amount = `round(abs(finding.impact), 2)`
- Payload includes `record_ids`, `table`, and `citations` from the story

### `list_fixes(conn, status=None) → list[dict]`
- Returns all drafts for the current tenant, optionally filtered by status
- Ordered by `created_at DESC`

### `get_fix(conn, fix_id) → dict | None`
- Fetches a single draft by UUID

### `decide_fix(conn, fix_id, actor, approve: bool, note) → dict`
- Only allowed when current status is `draft` (raises `ValueError` otherwise)
- Sets `status` to `approved` or `rejected`
- Records `decided_by`, `decided_at = now()`, `decision_note`
- Writes `audit_log` action `fix_approved` or `fix_rejected`

### `list_audit(conn, limit=200) → list[dict]`
- Returns audit entries for current tenant, newest first

### `log(conn, tenant_id, actor, action, target, details)`
- Low-level audit writer (used internally)

---

## API Routes (`app/fixes_routes.py`)

### HTML Routes (serve Jinja2 templates)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/leaks/{leak_id}/draft` | Create draft from story page, redirect to `/fixes` |
| `GET` | `/fixes` | Approval queue with tabs (draft/approved/rejected/all) |
| `POST` | `/fixes/{fix_id}/approve` | Approve with optional note, redirect to `/fixes` |
| `POST` | `/fixes/{fix_id}/reject` | Reject with optional note, redirect to `/fixes` |
| `GET` | `/audit` | Audit log table, newest first |

**Authentication:** Uses `dashboard_user` — unauthenticated requests redirect to `/login` (303).

### JSON API Routes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/fixes` | Create draft `{leak_id: int}` → 201 with draft |
| `GET` | `/api/fixes?status=` | List drafts, optional filter |
| `POST` | `/api/fixes/{id}/decision` | `{approve: bool, note: str}` → 200 or 409 |
| `GET` | `/api/audit?limit=200` | Audit log entries |

**Authentication:** Returns 401 if unauthenticated.

---

## Templates

### `fixes.html`
- Extends `base.html`
- Tab navigation by status
- Table with: Title, Check, Customer, Amount (formatted via `inr()`), Status badge, Created By, Created At, Actions
- For drafts: inline forms with optional note field for Approve/Reject
- For decided: shows decider and note

### `audit.html`
- Extends `base.html`
- Table: Time, Actor, Action (code), Target, Details (pretty-printed JSON)

### `story.html` (updated)
- Added form at bottom: `POST /leaks/{{ leak_id }}/draft` with "Draft a fix" button

---

## Testing (`tests/test_step7_fixes.py`)

Tests cover:
1. **API auth required** — 401 without login
2. **Create draft via API** — status=draft, amount matches finding impact
3. **Idempotent creation** — same leak_key returns same ID, only one `draft_created` audit entry
4. **Approve flow** — status=approved, decided_by set, `fix_approved` audit entry
5. **Double-decide** — 409 on second decision
6. **Reject flow** — status=rejected, `fix_rejected` audit entry
7. **HTML pages render** — `/fixes` and `/audit` return 200 with expected content
8. **HTML auth redirect** — `/fixes` unauthenticated → 303 to `/login`
9. **Audit log append-only** — UPDATE on `audit_log` raises `InsufficientPrivilege` when connected as `revenuelens_app` (skipped otherwise)

**Test Isolation:**
- Module fixture loads simulation data once
- Module fixture clears `fix_draft` at start (with RLS `app.tenant_id` set)
- Each test uses a different `leak_id` (0, 1, 2, 3, 4)
- Dashboard cache reset between tests

---

## Security Notes

- All database access goes through `company_conn()` which sets `app.tenant_id` for RLS
- The `revenuelens_app` database role cannot UPDATE or DELETE from `audit_log`
- Fix drafts are tenant-isolated via RLS FORCE policies
- Actor identity comes from authenticated session (email)

---

## What This Does NOT Do

- ❌ Write to the legacy billing system
- ❌ Execute the proposed fix automatically
- ❌ Send notifications (email, Slack, etc.)
- ❌ Provide a "rollback" for approved fixes (a new draft would be created)

The approved fix is a **record of intent**. Downstream systems or human operators consume the `fix_draft` table (status=approved) to perform the actual correction in the billing system.

---

## Next Steps

- Step 8: Export approved fixes as CSV/JSON for downstream consumption
- Step 9: Webhook/callback when a fix is approved
- Step 10: Dashboard metrics (total drafts, approval rate, time-to-decision)
