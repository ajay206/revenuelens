from __future__ import annotations

import os
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege

from app.main import app

# Module-level setup: ensure RL_LLM=fake and load simulation data
os.environ["RL_LLM"] = "fake"

# Database URL for legacy simulation
LEGACY_DATABASE_URL = os.environ.get("LEGACY_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/legacydb")
COMPANY_ID = os.environ.get("COMPANY_ID", "00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="module", autouse=True)
def load_sim_data():
    """Load simulation data once per module."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "legacy_sim.__main__", "load", "--database-url", LEGACY_DATABASE_URL],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to load sim data: {result.stderr}")

    # Clear fix_draft table before tests (RLS FORCE applies, so set app.tenant_id)
    with psycopg.connect(LEGACY_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (COMPANY_ID,))
            cur.execute("DELETE FROM fix_draft")
        conn.commit()

    # Reset dashboard cache
    from app.dashboard import reset_cache
    reset_cache()

    yield

    # Cleanup after module
    with psycopg.connect(LEGACY_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (COMPANY_ID,))
            cur.execute("DELETE FROM fix_draft")
        conn.commit()


@pytest.fixture
def client(seeded):
    """Test client with seeded database."""
    from app.dashboard import reset_cache
    reset_cache()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    """Authenticated test client."""
    resp = client.post("/login", data={"email": "admin@acme.test", "password": "s3cret-pass"})
    assert resp.status_code == 303
    # Follow redirect to get cookie
    client.cookies.update(resp.cookies)
    return client


def test_api_requires_auth(client: TestClient):
    """API endpoints require authentication."""
    resp = client.post("/api/fixes", json={"leak_id": 0})
    assert resp.status_code == 401

    resp = client.get("/api/fixes")
    assert resp.status_code == 401

    resp = client.get("/api/audit")
    assert resp.status_code == 401


def test_create_draft_api(auth_client: TestClient):
    """Create a fix draft via API returns draft status and correct amount."""
    # First get a finding to know expected amount
    resp = auth_client.get("/api/findings")
    assert resp.status_code == 200
    findings = resp.json()
    assert len(findings) > 0
    finding = findings[0]
    expected_amount = round(abs(finding["impact"]), 2)

    # Create draft
    resp = auth_client.post("/api/fixes", json={"leak_id": 0})
    assert resp.status_code == 201
    draft = resp.json()

    assert draft["status"] == "draft"
    assert float(draft["amount"]) == expected_amount
    assert draft["check_name"] == finding["check"]
    assert draft["created_by"] == "admin@acme.test"
    assert "id" in draft
    return draft["id"]


def test_create_draft_idempotent(auth_client: TestClient):
    """Creating draft twice for same leak returns same ID and only one audit entry."""
    # First creation
    resp1 = auth_client.post("/api/fixes", json={"leak_id": 1})
    assert resp1.status_code == 201
    draft1 = resp1.json()

    # Second creation
    resp2 = auth_client.post("/api/fixes", json={"leak_id": 1})
    assert resp2.status_code == 201
    draft2 = resp2.json()

    assert draft1["id"] == draft2["id"]

    # Check audit log - should have only one 'draft_created' for this leak_key
    resp_audit = auth_client.get("/api/audit")
    assert resp_audit.status_code == 200
    entries = resp_audit.json()["entries"]
    draft_created = [e for e in entries if e["action"] == "draft_created" and e["target"] == draft1["id"]]
    assert len(draft_created) == 1


def test_approve_flow(auth_client: TestClient):
    """Approve a draft -> approved with decided_by and audit has fix_approved."""
    # Create draft for a different leak
    resp = auth_client.post("/api/fixes", json={"leak_id": 2})
    assert resp.status_code == 201
    draft = resp.json()
    fix_id = draft["id"]

    # Approve
    resp = auth_client.post(f"/api/fixes/{fix_id}/decision", json={"approve": True, "note": "Looks good"})
    assert resp.status_code == 200
    approved = resp.json()

    assert approved["status"] == "approved"
    assert approved["decided_by"] == "admin@acme.test"
    assert approved["decision_note"] == "Looks good"
    assert approved["decided_at"] is not None

    # Check audit log
    resp_audit = auth_client.get("/api/audit")
    entries = resp_audit.json()["entries"]
    fix_approved = [e for e in entries if e["action"] == "fix_approved" and e["target"] == fix_id]
    assert len(fix_approved) == 1
    assert fix_approved[0]["details"]["note"] == "Looks good"


def test_decide_twice_returns_409(auth_client: TestClient):
    """Deciding on an already decided fix returns 409."""
    # Create and approve
    resp = auth_client.post("/api/fixes", json={"leak_id": 3})
    assert resp.status_code == 201
    fix_id = resp.json()["id"]

    auth_client.post(f"/api/fixes/{fix_id}/decision", json={"approve": True, "note": "First"})

    # Try to reject
    resp = auth_client.post(f"/api/fixes/{fix_id}/decision", json={"approve": False, "note": "Second"})
    assert resp.status_code == 409


def test_reject_flow(auth_client: TestClient):
    """Reject flow on another leak."""
    resp = auth_client.post("/api/fixes", json={"leak_id": 4})
    assert resp.status_code == 201
    fix_id = resp.json()["id"]

    resp = auth_client.post(f"/api/fixes/{fix_id}/decision", json={"approve": False, "note": "Not applicable"})
    assert resp.status_code == 200
    rejected = resp.json()

    assert rejected["status"] == "rejected"
    assert rejected["decided_by"] == "admin@acme.test"
    assert rejected["decision_note"] == "Not applicable"

    # Check audit
    resp_audit = auth_client.get("/api/audit")
    entries = resp_audit.json()["entries"]
    fix_rejected = [e for e in entries if e["action"] == "fix_rejected" and e["target"] == fix_id]
    assert len(fix_rejected) == 1


def test_fixes_html_page(auth_client: TestClient):
    """HTML /fixes page renders 200 and shows title."""
    resp = auth_client.get("/fixes")
    assert resp.status_code == 200
    assert "Fix Approval Queue" in resp.text


def test_audit_html_page(auth_client: TestClient):
    """HTML /audit page renders 200 and shows entries."""
    resp = auth_client.get("/audit")
    assert resp.status_code == 200
    assert "Audit Log" in resp.text


def test_fixes_html_unauthenticated(client: TestClient):
    """GET /fixes unauthenticated redirects to login."""
    resp = client.get("/fixes", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers.get("location", "")


def test_audit_log_append_only():
    """audit_log is append-only for revenuelens_app user."""
    # Check current DB user
    with psycopg.connect(LEGACY_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            current_user = cur.fetchone()[0]

    if current_user != "revenuelens_app":
        pytest.skip(f"Test only runs as revenuelens_app, current user: {current_user}")

    # Try to UPDATE audit_log as revenuelens_app - should fail
    with psycopg.connect(LEGACY_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (COMPANY_ID,))
            # Insert a test row first
            cur.execute("""
                INSERT INTO audit_log (tenant_id, actor, action, target, details)
                VALUES (%s, 'test', 'test_action', 'test_target', '{}')
                RETURNING id
            """, (COMPANY_ID,))
            test_id = cur.fetchone()[0]
            conn.commit()

            # Now try to update it
            with pytest.raises(InsufficientPrivilege):
                cur.execute("UPDATE audit_log SET action = 'hacked' WHERE id = %s", (test_id,))
            conn.rollback()

            # Cleanup
            cur.execute("DELETE FROM audit_log WHERE id = %s", (test_id,))
            conn.commit()
