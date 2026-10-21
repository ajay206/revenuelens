import os

import pytest
from fastapi.testclient import TestClient

from app import seed
from app.main import app

# Set default environment variables for the test suite
os.environ.setdefault("COMPANY_ID", "11111111-1111-1111-1111-111111111111")
os.environ.setdefault("COMPANY_NAME", "Acme Test")
os.environ.setdefault("JWT_SECRET", "test-secret-a")
os.environ.setdefault("ADMIN_EMAIL", "admin@acme.test")
os.environ.setdefault("ADMIN_PASSWORD", "s3cret-pass")

import psycopg

from app.migrate import main as run_migrations


@pytest.fixture(scope="session")
def db():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set")
    try:
        conn = psycopg.connect(database_url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Unable to connect to Postgres: {exc}")

    # Run migrations
    run_migrations()

    yield conn

    conn.close()


@pytest.fixture(scope="session")
def seeded(db):
    # Run the seed script to ensure tenant and admin user exist
    seed.main()
    return db


@pytest.fixture
def client():
    return TestClient(app)
