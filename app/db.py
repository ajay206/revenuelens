import os
from contextlib import contextmanager

import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://revenuelens:revenuelens@localhost:5432/revenuelens",
)


def get_conn() -> psycopg.Connection:
    """Return a new psycopg (v3) connection using the configured DATABASE_URL."""
    return psycopg.connect(DATABASE_URL)


@contextmanager
def tenant_conn(tenant_id: str):
    """Context manager that sets the RLS tenant context for the duration of the connection.

    Uses ``set_config('app.tenant_id', %s, false)`` so that all subsequent
    queries within the same transaction/tenant context are correctly scoped
    by the Row Level Security policies defined in the schema.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, false)",
                (str(tenant_id),),
            )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
