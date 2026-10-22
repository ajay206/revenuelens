import os

import pytest

# Ensure the fake LLM environment variable is set before any imports that may use it
os.environ["RL_LLM"] = "fake"

from app.answer_key import compare
from app.reconcile import Finding
from legacy_sim.generator import LEAK_TYPES, generate, random_leak_counts


def _ground_truth_signature(gt: list[dict]) -> set[tuple[str, tuple[str, ...]]]:
    """Create a signature set from ground‑truth entries for comparison."""
    return {
        (entry["type"], tuple(sorted(entry["record_ids"])))
        for entry in gt
    }


def test_generate_variability():
    seeds = [1, 2, 3]
    signatures = [_ground_truth_signature(generate(seed=s, randomize=True).ground_truth) for s in seeds]
    # Not all signatures should be equal
    assert not (signatures[0] == signatures[1] == signatures[2])
    # Same seed should produce identical signature
    sig_a = _ground_truth_signature(generate(seed=42, randomize=True).ground_truth)
    sig_b = _ground_truth_signature(generate(seed=42, randomize=True).ground_truth)
    assert sig_a == sig_b


def test_random_leak_counts_distribution():
    counts = random_leak_counts(12345)
    # Ensure we have counts for each of the 8 leak types
    assert set(counts.keys()) == set(LEAK_TYPES)
    # At least four types must have a non‑zero count
    non_zero = sum(1 for v in counts.values() if v > 0)
    assert non_zero >= 4
    # Values lie within the expected range
    for v in counts.values():
        assert 0 <= v <= 8


def test_compare_logic():
    # Build two fake findings, one matching and one false positive
    f1 = Finding(
        check="duplicate_bill",
        record_ids=["rec1", "rec2"],
        table="billing",
        customer_id="CUST123",
        period="202608",
        impact=1000.0,
        evidence={},
        description="Dup bill",
    )
    f2 = Finding(
        check="missing_tax",
        record_ids=["recX"],
        table="tax",
        customer_id="CUST999",
        period="202607",
        impact=500.0,
        evidence={},
        description="Tax missing",
    )
    # Planted issues – only one of the types above is planted
    planted = [
        {
            "leak_id": "L1",
            "check_name": "duplicate_bill",
            "table_name": "billing",
            "record_ids": ["rec2", "rec3"],
            "bill_prd": "202608",
            "impact_inr": 1200.0,
            "description": "Duplicate",
            "cust_no": "CUST123",
        }
    ]

    report = compare(planted, [f1, f2])

    # One planted issue, matched by f1 (shared rec2)
    assert report["planted"] == 1
    assert report["detected"] == 1
    assert report["missed"] == 0
    # f2 is a false positive (no matching planted issue of same check)
    assert len(report["false_positives"]) == 1
    fp = report["false_positives"][0]
    assert fp["index"] == 1
    assert fp["check"] == "missing_tax"

    # Precision = TP / (TP + FP) = 1 / 2 = 0.5
    assert pytest.approx(report["precision"], rel=1e-4) == 0.5
    # Recall = TP / Planted = 1 / 1 = 1.0
    assert report["recall"] == 1.0


# ----------------------------------------------------------------------
# Integration tests that require a real PostgreSQL instance
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_url():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set – skipping DB integration tests")
    return url


@pytest.fixture(scope="module")
def setup_demo(db_url):
    # Run migrations and seed the demo database
    import app.migrate
    import app.seed

    app.migrate.main()
    app.seed.main()

    # Point legacy dashboard to the same DB
    os.environ["LEGACY_DATABASE_URL"] = db_url

    yield

    # Teardown: reload default data and clear planted tables
    import legacy_sim.__main__

    legacy_sim.__main__.main(
        ["load", "--database-url", db_url, "--seed", "42"]
    )
    from app.dashboard import reset_cache

    reset_cache()
    # Clear answer‑key tables for the tenant used in tests
    from app.db import company_conn

    with company_conn() as conn:
        tenant_id = os.environ["COMPANY_ID"]
        conn.execute(
            "DELETE FROM planted_issue WHERE tenant_id = %s", (tenant_id,)
        )
        conn.execute(
            "DELETE FROM demo_run WHERE tenant_id = %s", (tenant_id,)
        )
        conn.commit()


def test_recall_over_seeds(setup_demo):
    from fastapi.testclient import TestClient

    from app.answer_key import compare, store_planted
    from app.dashboard import load_findings, reset_cache
    from app.db import company_conn
    from app.main import app

    client = TestClient(app)

    # Login once (admin credentials expected in env)
    login_resp = client.post(
        "/login",
        data={
            "email": os.getenv("ADMIN_EMAIL"),
            "password": os.getenv("ADMIN_PASSWORD"),
        },
        follow_redirects=False,
    )
    assert login_resp.status_code == 303

    for seed in (7, 123, 2024):
        # Load demo data with randomization
        import legacy_sim.__main__

        legacy_sim.__main__.main(
            [
                "load",
                "--database-url",
                os.getenv("DATABASE_URL"),
                "--seed",
                str(seed),
                "--randomize",
            ]
        )
        reset_cache()
        findings = load_findings()

        gt = generate(seed=seed, randomize=True).ground_truth
        planted = [
            {
                "leak_id": g["leak_id"],
                "check_name": g["type"],
                "table_name": g.get("table"),
                "record_ids": g["record_ids"],
                "bill_prd": g.get("bill_prd"),
                "impact_inr": g.get("impact_inr"),
                "description": g.get("description"),
                "cust_no": g.get("cust_no"),
            }
            for g in gt
            if g["type"] in LEAK_TYPES
        ]

        with company_conn() as conn:
            tenant_id = os.environ["COMPANY_ID"]
            store_planted(conn, tenant_id, seed, gt)

        report = compare(planted, findings)
        assert report["recall"] == 1.0
        # Ensure per‑check stats exist for all leak types
        for check in LEAK_TYPES:
            assert check in report["per_check"]


def test_answer_key_endpoint(setup_demo):
    from fastapi.testclient import TestClient

    from app.answer_key import store_planted
    from app.db import company_conn
    from app.main import app

    client = TestClient(app)

    # Authenticate
    resp = client.post(
        "/login",
        data={
            "email": os.getenv("ADMIN_EMAIL"),
            "password": os.getenv("ADMIN_PASSWORD"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Load a deterministic demo
    seed = 7
    import legacy_sim.__main__

    legacy_sim.__main__.main(
        [
            "load",
            "--database-url",
            os.getenv("DATABASE_URL"),
            "--seed",
            str(seed),
            "--randomize",
        ]
    )
    with company_conn() as conn:
        tenant_id = os.environ["COMPANY_ID"]
        gt = generate(seed=seed, randomize=True).ground_truth
        store_planted(conn, tenant_id, seed, gt)

    # API endpoint
    api_resp = client.get("/api/answer-key")
    assert api_resp.status_code == 200
    data = api_resp.json()
    assert data["seed"] == seed
    assert data["planted"] == len([g for g in gt if g["type"] in LEAK_TYPES])
    assert data["recall"] == 1.0

    # HTML page
    html_resp = client.get("/planted")
    assert html_resp.status_code == 200
    assert "Planted issues" in html_resp.text

    # Unauthenticated access
    unauth_client = TestClient(app)
    unauth_resp = unauth_client.get("/api/answer-key")
    assert unauth_resp.status_code == 401


def test_login_errors(setup_demo):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    # Missing password
    resp = client.post(
        "/login",
        data={"email": "a@b.c", "password": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "Enter your email and password" in resp.text
    assert '"detail"' not in resp.text

    # Wrong password (assuming admin credentials are set)
    resp = client.post(
        "/login",
        data={"email": os.getenv("ADMIN_EMAIL", "admin@example.com"), "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Wrong email or password" in resp.text
