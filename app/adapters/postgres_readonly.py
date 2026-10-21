"""Read-only PostgreSQL adapter using psycopg v3."""

from __future__ import annotations

from typing import Self

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import SQL, Composable, Identifier


class ReadOnlyAdapter:
    """Read-only adapter for PostgreSQL database."""

    def __init__(self, dsn: str, schema: str) -> None:
        self.conn = psycopg.connect(
            dsn,
            options="-c default_transaction_read_only=on",
            row_factory=dict_row,
        )
        self.schema = schema

    def list_tables(self) -> list[str]:
        """Return sorted list of base tables in the schema."""
        sql = SQL(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, (self.schema,))
            rows = cur.fetchall()
        self.conn.rollback()
        return [row["table_name"] for row in rows]

    def columns(self, table: str) -> list[tuple[str, str]]:
        """Return list of (column_name, data_type) by ordinal position."""
        sql = SQL(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, (self.schema, table))
            rows = cur.fetchall()
        self.conn.rollback()
        return [(row["column_name"], row["data_type"]) for row in rows]

    def row_count(self, table: str) -> int:
        """Return row count for a table."""
        sql = SQL("SELECT COUNT(*) AS cnt FROM {}.{}").format(
            Identifier(self.schema), Identifier(table)
        )
        with self.conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        self.conn.rollback()
        return row["cnt"] if row else 0

    def sample(self, table: str, n: int = 5) -> list[dict]:
        """Return up to n sample rows from a table."""
        sql = SQL("SELECT * FROM {}.{} LIMIT %s").format(
            Identifier(self.schema), Identifier(table)
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, (n,))
            rows = cur.fetchall()
        self.conn.rollback()
        return rows

    def fetch_all(self, table: str, columns: list[str] | None = None) -> list[dict]:
        """Return all rows from a table, optionally selecting specific columns."""
        if columns:
            col_sql = SQL(", ").join(Identifier(c) for c in columns)
            sql = SQL("SELECT {} FROM {}.{}").format(
                col_sql, Identifier(self.schema), Identifier(table)
            )
        else:
            sql = SQL("SELECT * FROM {}.{}").format(
                Identifier(self.schema), Identifier(table)
            )
        with self.conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        self.conn.rollback()
        return rows

    def query(self, sql: str | Composable, params: tuple | list | None = None) -> list[dict]:
        """Execute a SELECT-only query and return rows."""
        text = sql if isinstance(sql, str) else sql.as_string(self.conn)
        stripped = text.strip().lower()
        if not stripped.startswith(("select", "with")):
            raise ValueError("Only SELECT or WITH queries are allowed")
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        self.conn.rollback()
        return rows

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
