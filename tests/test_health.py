from fastapi.testclient import TestClient


def test_health(client: TestClient, seeded):
    response = client.get("/health")
    assert response.status_code == 200
    json_body = response.json()
    assert json_body["status"] == "ok"
