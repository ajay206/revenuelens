import pathlib

import psycopg
from psycopg import sql

from app.db import get_conn

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations"


def ensure_migration_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY
        );
        """
    )


def applied_versions(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
    return {row[0] for row in rows}


def apply_migration(conn: psycopg.Connection, version: str, content: str) -> None:
    conn.execute(sql.SQL(content))
    conn.execute(
        "INSERT INTO schema_migrations (version) VALUES (%s);", (version,)
    )
    # Commit after each migration to persist changes
    conn.commit()


def main() -> None:
    conn = get_conn()
    ensure_migration_table(conn)

    applied = applied_versions(conn)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for path in sql_files:
        version = path.name
        if version in applied:
            continue
        content = path.read_text()
        apply_migration(conn, version, content)
        print(f"Applied migration {version}")


if __name__ == "__main__":
    main()
