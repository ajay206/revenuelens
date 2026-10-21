"""CSV export adapter backed by an in-memory DuckDB connection.

Mimics the :class:`~app.adapters.postgres_readonly.ReadOnlyAdapter` interface so
that :func:`app.discovery.discover`, :func:`app.mapping.map_schema` and
:func:`app.reconcile.run_checks` work unchanged against a directory of CSV files
produced by ``python -m legacy_sim generate --out DIR``.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import duckdb
from psycopg.sql import Composable


class CsvExportAdapter:
    """Read-only adapter over a directory of CSV files using DuckDB."""

    def __init__(self, dir_path: str | os.PathLike[str], schema: str = "nimbus") -> None:
        self.dir_path = str(dir_path)
        self.schema = schema
        self.conn = duckdb.connect()
        # Ensure the target schema exists.
        self.conn.execute("CREATE SCHEMA IF NOT EXISTS {}".format(schema))
        # Load every CSV file into a table named after its (lowercased) stem.
        for csv_path in sorted(Path(self.dir_path).glob("*.csv")):
            table = csv_path.stem.lower()
            full_path = str(csv_path)
            self.conn.execute(
                "CREATE TABLE {}.\"{}\" AS "
                "SELECT * FROM read_csv_auto(?, header=true)".format(schema, table),
                [full_path],
            )

    # ------------------------------------------------------------------ #
    # Schema introspection helpers
    # ------------------------------------------------------------------ #
    def _table_fqn(self, table: str) -> str:
        """Return a fully-qualified quoted table identifier."""
        return "{}.\"{}\"".format(self.schema, table)

    @staticmethod
    def _map_type(duck_type: str) -> str:
        """Map a DuckDB type name to a PostgreSQL-style ``data_type`` string."""
        t = duck_type.upper()
        if t in ("BIGINT", "INTEGER", "HUGEINT", "SMALLINT"):
            return "integer"
        if t.startswith("DECIMAL"):
            return "numeric"
        if t in ("DOUBLE", "FLOAT"):
            return "numeric"
        if t == "DATE":
            return "date"
        if t.startswith("TIMESTAMP"):
            return "timestamp without time zone"
        if t == "BOOLEAN":
            return "boolean"
        if t == "VARCHAR":
            return "character varying"
        return duck_type.lower()

    # ------------------------------------------------------------------ #
    # Public interface (mirrors ReadOnlyAdapter)
    # ------------------------------------------------------------------ #
    def list_tables(self) -> list[str]:
        """Return sorted list of base tables in the schema."""
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            [self.schema],
        ).fetchall()
        self.conn.rollback()
        return [r[0] for r in rows]

    def columns(self, table: str) -> list[tuple[str, str]]:
        """Return list of ``(column_name, data_type)`` by ordinal position."""
        rows = self.conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            [self.schema, table],
        ).fetchall()
        self.conn.rollback()
        return [(r[0], self._map_type(r[1])) for r in rows]

    def row_count(self, table: str) -> int:
        """Return row count for a table."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM {}".format(self._table_fqn(table))
        ).fetchone()
        self.conn.rollback()
        return int(row[0]) if row else 0

    def sample(self, table: str, n: int = 5) -> list[dict]:
        """Return up to *n* sample rows from a table."""
        rows = self.conn.execute(
            "SELECT * FROM {} LIMIT ?".format(self._table_fqn(table)), [n]
        ).fetchdf()
        self.conn.rollback()
        return self._to_dicts(rows)

    def fetch_all(self, table: str, columns: list[str] | None = None) -> list[dict]:
        """Return all rows from a table, optionally selecting specific columns."""
        if columns:
            cols = ", ".join('"{}"'.format(c) for c in columns)
            sql = "SELECT {} FROM {}".format(cols, self._table_fqn(table))
        else:
            sql = "SELECT * FROM {}".format(self._table_fqn(table))
        rows = self.conn.execute(sql).fetchdf()
        self.conn.rollback()
        return self._to_dicts(rows)

    def query(self, sql: str | Composable, params: tuple | list | None = None) -> list[dict]:
        """Execute a ``SELECT``/``WITH`` query and return rows as list of dicts."""
        text = sql if isinstance(sql, str) else sql.as_string(None)
        stripped = text.strip().lower()
        if not stripped.startswith(("select", "with")):
            raise ValueError("Only SELECT or WITH queries are allowed")
        params_list = list(params) if params is not None else []
        rows = self.conn.execute(text, params_list).fetchdf()
        self.conn.rollback()
        return self._to_dicts(rows)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self.conn.close()

    # ------------------------------------------------------------------ #
    # Context-manager / dunder helpers
    # ------------------------------------------------------------------ #
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Internal conversion helpers
    # ------------------------------------------------------------------ #
    def _to_dicts(self, df: Any) -> list[dict]:
        """Convert a DuckDB DataFrame result into a list of typed dicts."""
        if df is None or len(df) == 0:
            return []
        records: list[dict] = []
        columns_iter = df.columns
        for _, row in df.iterrows():
            record: dict[str, Any] = {}
            for col in columns_iter:
                value = row[col]
                record[col] = self._convert_value(value)
            records.append(record)
        return records

    def _convert_value(self, value: Any) -> Any:
        """Convert a single Python value extracted from a DuckDB DataFrame."""
        if value is None:
            return None
        # Decimal handling – mimic psycopg rounding to 4 decimal places.
        if isinstance(value, Decimal):
            return Decimal(str(round(float(value), 4)))
        # Float -> numeric column values become Decimal via Decimal(str(round(...)))
        if isinstance(value, float):
            return Decimal(str(round(value, 4)))
        # Dates/timestamps already come back nicely typed by DuckDB
        return value
