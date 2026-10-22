import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.main
import app.migrate
import app.registration as reg_module
import app.seed


@pytest.fixture(scope="module", autouse=True)
def _setup_db() -> None:
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
    tenant_id = os.getenv("COMPANY_ID")
    if not tenant_id:
        yield
        return
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        yield
        return

    def _delete() -> None:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cur.execute("DELETE FROM app_user WHERE username IS NOT NULL")
            conn.commit()

    _delete()
    yield
    _delete()


def test_validate_short_username() -> None:
    with pytest.raises(reg_module.RegistrationError) as exc:
        reg_module.validate("ab", "longpass", "longpass")
    assert exc.value.status_code == 422
    assert "3–32" in exc.value.message


def test_validate_bad_chars() -> None:
    with pytest.raises(reg_module.RegistrationError) as exc:
        reg_module.validate("user@name", "longpass", "longpass")
    assert exc.value.status_code == 422


def test_validate_short_password() -> None:
    with pytest.raises(reg_module.RegistrationError) as exc:
        reg_module.validate("validuser", "short", "short")
    assert exc.value.status_code == 422
    assert "8 characters" in exc.value.message


def test_validate_mismatch() -> None:
    with pytest.raises(reg_module.RegistrationError) as exc:
        reg_module.validate("validuser", "longpass1", "longpass2")
    assert exc.value.status_code == 422
    assert "match" in exc.value.message


def test_register_ok(client: TestClient) -> None:
    resp = client.post(
        "/auth/register",
        json={"username": "alice_1", "password": "longpass1", "confirm_password": "longpass1"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice_1"
    assert data["role"] == "viewer"
    assert "id" in data


def test_duplicate_case_insensitive(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"username": "Bob.Smith", "password": "longpass1", "confirm_password": "longpass1"},
    )
    resp = client.post(
        "/auth/register",
        json={"username": "bob.smith", "password": "otherpass", "confirm_password": "otherpass"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "That username is already taken"


def test_weak_password_html(client: TestClient) -> None:
    resp = client.post(
        "/register",
        data={"username": "carol", "password": "short", "confirm_password": "short"},
    )
    assert resp.status_code == 422
    assert "text/html" in resp.headers.get("content-type", "")
    assert "at least 8 characters" in resp.text.lower()
    assert '"detail"' not in resp.text


def test_taken_username_html(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"username": "dave", "password": "longpass1", "confirm_password": "longpass1"},
    )
    resp = client.post(
        "/register",
        data={"username": "DAVE", "password": "longpass1", "confirm_password": "longpass1"},
    )
    assert resp.status_code == 409
    assert "text/html" in resp.headers.get("content-type", "")
    assert "That username is already taken" in resp.text


def test_login_by_username(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"username": "erin", "password": "longpass1", "confirm_password": "longpass1"},
    )
    resp = client.post(
        "/login",
        data={"email": "erin", "password": "longpass1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "rl_token" in resp.cookies

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    if admin_email and admin_pass:
        resp2 = client.post(
            "/login",
            data={"email": admin_email, "password": admin_pass},
            follow_redirects=False,
        )
        assert resp2.status_code == 303
        assert "rl_token" in resp2.cookies


def test_viewer_cannot_approve(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"username": "frank", "password": "longpass1", "confirm_password": "longpass1"},
    )
    # API login
    resp = client.post(
        "/auth/login",
        json={"email": "frank", "password": "longpass1"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    fix_id = "00000000-0000-0000-0000-000000000000"
    resp2 = client.post(
        f"/api/fixes/{fix_id}/decision",
        json={"approve": True, "note": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 403

    # Form login with cookie
    client2 = TestClient(app.main.app)
    resp3 = client2.post(
        "/login",
        data={"email": "frank", "password": "longpass1"},
        follow_redirects=False,
    )
    assert resp3.status_code == 303
    resp4 = client2.post(
        f"/fixes/{fix_id}/approve",
        follow_redirects=False,
    )
    assert resp4.status_code == 403


def test_registration_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_REGISTRATION", "false")
    # Need to reload module to pick up new env
    import importlib
    importlib.reload(reg_module)
    try:
        resp = client.post(
            "/auth/register",
            json={"username": "disabled", "password": "longpass1", "confirm_password": "longpass1"},
        )
        assert resp.status_code == 403
        assert "turned off" in resp.json()["detail"]
    finally:
        monkeypatch.setenv("ALLOW_REGISTRATION", "true")
        importlib.reload(reg_module)


def test_registration_audited(client: TestClient) -> None:
    tenant_id = os.getenv("COMPANY_ID")
    db_url = os.getenv("DATABASE_URL")
    assert tenant_id and db_url

    client.post(
        "/auth/register",
        json={"username": "gina", "password": "longpass1", "confirm_password": "longpass1"},
    )

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
        cur.execute(
            """
                SELECT 1 FROM audit_log
                WHERE action = 'user_registered' AND target = 'user:gina'
                LIMIT 1
                """
        )
        row = cur.fetchone()
        assert row is not None


def test_cross_tenant_isolation() -> None:
    tenant_id = os.getenv("COMPANY_ID")
    db_url = os.getenv("DATABASE_URL")
    if not tenant_id or not db_url:
        pytest.skip("COMPANY_ID or DATABASE_URL not set")

    other_tenant = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        try:
            cur.execute("SET ROLE revenuelens_app")
        except Exception:  # noqa: BLE001
            pytest.skip("revenuelens_app role not available")
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (other_tenant,))
        cur.execute("SELECT count(*) FROM app_user WHERE username IS NOT NULL")
        count = cur.fetchone()[0]
        assert count == 0
