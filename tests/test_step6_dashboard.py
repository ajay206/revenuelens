import os

import pytest
from app.reconcile import Finding
from fastapi.testclient import TestClient

from app import dashboard
from app.main import app
from app.security import create_token


def inr(value: float) -> str:
    return f"₹{abs(value):,.2f}"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def sim_loaded(db_url):
    from legacy_sim.__main__ import main as sim_main

    sim_main(["load", "--database-url", db_url])
    os.environ["LEGACY_DATABASE_URL"] = db_url
    os.environ["RL_LLM"] = "fake"
    dashboard.reset_cache()


@pytest.fixture(scope="module")
def seeded():
    # creates admin admin@acme.test / s3cret-pass if needed
    from app.db import company_conn
    from app.security import hash_password

    with company_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM app_user WHERE email = %s AND tenant_id = 1",
            ("admin@acme.test",),
        )
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO app_user (tenant_id, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (1, "admin@acme.test", hash_password("s3cret-pass"), "admin"),
            )
            conn.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_token():
    token = create_token(sub="1", tenant_id=1)
    return token


# --------------------------------------------------------------------------- #
# Unit tests (no DB)
# --------------------------------------------------------------------------- #


def test_compute_totals_unit():
    findings = [
        Finding(check="a", record_ids=["r1"], table="t", customer_id="c1", period="2024-01", impact=100.0, evidence={}, description="d1"),
        Finding(check="b", record_ids=["r2"], table="t", customer_id="c2", period="2024-01", impact=-30.0, evidence={}, description="d2"),
        Finding(check="c", record_ids=["r3"], table="t", customer_id="c3", period="2023-12", impact=-50.0, evidence={}, description="d3"),
    ]
    totals = dashboard.compute_totals(findings)
    assert totals["found_total"] == 180.0
    assert totals["month_total"] == 130.0
    assert totals["latest_period"] == "2024-01"
    assert totals["count"] == 3


def test_inr_unit():
    assert dashboard.inr(1234567.89) == "₹1,23,4567.89"


# --------------------------------------------------------------------------- #
# Integration tests
# --------------------------------------------------------------------------- #


@pytest.fixture()
def require_db(sim_loaded, seeded):
    return True


def test_get_root_without_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_api_findings_no_auth(client):
    r = client.get("/api/findings")
    assert r.status_code == 401


def test_post_login_wrong_password(client):
    r = client.post("/login", data={"email": "admin@acme.test", "password": "wrong"}, follow_redirects=False)
    assert r.status_code == 401


def test_login_and_access_dashboard(client):
    r = client.post(
        "/login",
        data={"email": "admin@acme.test", "password": "s3cret-pass"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.cookies.get("rl_token")
    r2 = client.get("/", follow_redirects=True)
    assert r2.status_code == 200
    assert "leaking this month" in r2.text


def test_summary_matches_findings(client):
    r = client.get("/api/findings")
    assert r.status_code == 200
    findings_data = r.json()
    expected = round(sum(abs(f["impact"]) for f in findings_data), 2)
    summary = client.get("/api/summary").json()
    assert summary["found_total"] == expected
    assert summary["month_total"] <= summary["found_total"]


def test_home_shows_inr(client):
    r = client.get("/")
    assert r.status_code == 200
    expected = inr(round(sum(abs(f["impact"]) for f in client.get("/api/findings").json()), 2))
    assert expected in r.text


def test_story_page_sources(client):
    story = client.get("/api/stories/0").json()
    page = client.get("/leaks/0")
    assert page.status_code == 200
    assert "Sources" in page.text
    for c in story["citations"]:
        assert c["ref"] in page.text


def test_type_filter(client):
    all_findings = client.get("/api/findings").json()
    if not all_findings:
        pytest.skip("No findings")
    first_type = all_findings[0]["check"]
    filtered = client.get(f"/api/findings?type={first_type}").json()
    assert all(f["check"] == first_type for f in filtered)


def test_leak_404(client):
    r = client.get("/leaks/9999")
    assert r.status_code == 404
