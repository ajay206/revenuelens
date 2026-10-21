import datetime

import jwt
from fastapi.testclient import TestClient


def test_login_success(client: TestClient, seeded):
    response = client.post(
        "/auth/login",
        json={"email": "admin@acme.test", "password": "s3cret-pass"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    token = data["access_token"]

    # Use token to call /me
    me_resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "admin@acme.test"
    assert (
        me_data["company_id"]
        == "11111111-1111-1111-1111-111111111111"
    )


def test_login_wrong_password(client: TestClient, seeded):
    resp = client.post(
        "/auth/login",
        json={"email": "admin@acme.test", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_me_invalid_token_signature(client: TestClient, seeded):
    # Create a token signed with a wrong secret
    payload = {
        "sub": "some-id",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "exp": datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(minutes=60),
    }
    bad_token = jwt.encode(payload, "other-company-secret", algorithm="HS256")
    resp = client.get(
        "/me", headers={"Authorization": f"Bearer {bad_token}"}
    )
    assert resp.status_code == 401


def test_me_missing_token(client: TestClient, seeded):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_wrong_tenant(client: TestClient, seeded):
    # Token signed correctly but with a different tenant_id
    from app.config import get_settings

    settings = get_settings()
    payload = {
        "sub": "some-id",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "exp": datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(minutes=60),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    resp = client.get(
        "/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
