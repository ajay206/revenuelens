from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from .config import get_settings


def get_conn() -> psycopg.Connection:
    """Return a new psycopg (v3) connection using the configured DATABASE_URL."""
    return psycopg.connect(get_settings().database_url)


@contextmanager
def tenant_conn(tenant_id: str) -> Generator[psycopg.Connection, None, None]:
    """
    Context manager that sets the RLS tenant context for the duration of the
    connection. Uses ``set_config('app.tenant_id', %s, false)`` so that all
    subsequent queries within the same transaction/tenant context are correctly
    scoped by the Row Level Security policies defined in the schema.
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


def company_conn() -> Generator[psycopg.Connection, None, None]:
    """Convenience wrapper that uses the tenant_id from settings (the company)."""
    settings = get_settings()
    return tenant_conn(settings.company_id)
