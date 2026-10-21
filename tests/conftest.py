import os

import psycopg
import pytest

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
