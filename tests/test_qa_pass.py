import os
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.main
import app.migrate
import app.registration as reg_module
import app.seed
from app.demo_pipeline import _determine_seed

# ----------------------------------------------------------------------
# Database fixtures (copy from test_registration.py)
# ----------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _setup_db() -> None:
    """Create a fresh DB schema for the test run."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(db_url, connect_timeout=3):
            pass
    except Exception:  # noqa: BLE001
        pytest.skip("Cannot connect to database")

    app.migrate.main()
    app.seed.main()
    yield


@pytest.fixture(autouse=True)
def _enable_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure registration is allowed for the duration of the test."""
    original = os.getenv("ALLOW_REGISTRATION")
    monkeypatch.setenv("ALLOW_REGISTRATION", "true")
    reg_module.reset_rate_limit()
    yield
    if original is None:
        monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
    else:
        monkeypatch.setenv("ALLOW_REGISTRATION", original)
    reg_module.reset_rate_limit()


@pytest.fixture(autouse=True)
def _clean_test_users() -> None:
    """Delete any users created by the tests."""
    tenant_id = os.getenv("COMPANY_ID")
    db_url = os.getenv("DATABASE_URL")
    if not tenant_id or not db_url:
        yield
        return

    def _delete() -> None:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (tenant_id,)
                )
                cur.execute("DELETE FROM app_user WHERE username IS NOT NULL")
            conn.commit()

    _delete()
    yield
    _delete()


# ----------------------------------------------------------------------
# Helper – login and obtain a TestClient with session cookies
# ----------------------------------------------------------------------


def login_as(email: str, password: str) -> TestClient:
    client = TestClient(app.main.app)
    resp = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Login failed for {email}"
    return client


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_html_404_is_friendly() -> None:
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    assert admin_email and admin_pass, "ADMIN env vars missing"

    client = login_as(admin_email, admin_pass)

    # HTML route – friendly page
    html_resp = client.get("/does-not-exist", headers={"Accept": "text/html"})
    assert html_resp.status_code == 404
    assert "text/html" in html_resp.headers.get("content-type", "")
    text = html_resp.text
    assert "Page not found" in text
    assert '"detail"' not in text

    # API route – JSON error
    api_resp = client.get("/api/does-not-exist")
    assert api_resp.status_code == 404
    data = api_resp.json()
    assert "detail" in data


def test_profile_settings_links_removed() -> None:
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    client = login_as(admin_email, admin_pass)

    resp = client.get("/reports")
    assert resp.status_code == 200
    txt = resp.text
    assert 'href="/profile"' not in txt
    assert 'href="/settings"' not in txt


def test_viewer_sees_no_approve_buttons() -> None:
    # Register a viewer account
    register_resp = TestClient(app.main.app).post(
        "/auth/register",
        json={
            "username": "qa_viewer",
            "password": "longpass1",
            "confirm_password": "longpass1",
        },
    )
    assert register_resp.status_code == 201

    client = login_as("qa_viewer", "longpass1")

    fixes_resp = client.get("/fixes")
    assert fixes_resp.status_code == 200
    txt = fixes_resp.text
    assert "/approve" not in txt
    assert "/reject" not in txt

    # Viewer still gets the friendly HTML 404
    html_404 = client.get("/does-not-exist", headers={"Accept": "text/html"})
    assert html_404.status_code == 404
    assert "text/html" in html_404.headers.get("content-type", "")


def test_viewer_cannot_draft() -> None:
    TestClient(app.main.app).post(
        "/auth/register", json={"username": "qa_viewer2", "password": "longpass1", "confirm_password": "longpass1"}
    )
    client = login_as("qa_viewer2", "longpass1")
    resp = client.post("/api/fixes", json={"leak_id": 0})
    assert resp.status_code == 403


def test_demo_seed_warning(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Pure test – no DB needed."""
    # Force a non‑numeric DEMO_SEED
    monkeypatch.setenv("DEMO_SEED", "abc")

    # Mock _get_demo_seed to return None so _determine_seed falls back
    monkeypatch.setattr(
        "app.demo_pipeline._get_demo_seed",
        lambda conn: None,
    )

    class DummyConn:
        def cursor(self) -> Any:
            raise RuntimeError("no real DB")

    seed = _determine_seed(DummyConn())
    assert isinstance(seed, int)
    assert 1 <= seed <= 999_999

    captured = capsys.readouterr()
    assert "DEMO_SEED" in captured.err


def test_missed_renewal_has_bill_period() -> None:
    """Pure test – validate generator output."""
    from legacy_sim.generator import generate

    data = generate()
    for entry in data.ground_truth:
        if entry.get("type") == "missed_renewal":
            bill_prd = entry.get("bill_prd", "")
            assert isinstance(bill_prd, str) and bill_prd.isdigit() and len(bill_prd) == 6
