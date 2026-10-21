"""Discovery utilities for profiling database schemas.

This module defines data classes representing column, table, join, and
schema profiles and provides a ``discover`` function that inspects a
read‑only database adapter to produce a ``SchemaProfile`` instance.

The implementation follows the specification in the prompt:
* Profile the first ``sample_size`` rows of each table.
* Identify candidate keys as columns with a distinct ratio of ``1.0`` and
  a null ratio of ``0.0`` on the sampled data.
* Detect joins between tables based on shared column names where the
  right‑hand column is a candidate key.  The overlap metric is the
  fraction of distinct, non‑null values in the left column that appear
  in the right column.  Only joins with an overlap of at least ``0.5``
  are retained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import psycopg.sql as psql

# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #


@dataclass
class ColumnProfile:
    """Statistical profile for a single column."""

    name: str
    data_type: str
    distinct_ratio: float
    null_ratio: float
    samples: list[str] = field(default_factory=list)


@dataclass
class TableProfile:
    """Statistical profile for a table."""

    name: str
    row_count: int
    columns: list[ColumnProfile] = field(default_factory=list)
    candidate_keys: list[str] = field(default_factory=list)


@dataclass
class Join:
    """Potential join between two tables based on a shared column."""

    left_table: str
    left_col: str
    right_table: str
    right_col: str
    overlap: float


@dataclass
class SchemaProfile:
    """Aggregated schema profile."""

    schema: str
    tables: dict[str, TableProfile] = field(default_factory=dict)
    joins: list[Join] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a deep ``dict`` representation of the profile."""
        return asdict(self)


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _sample_table(
    adapter: Any,
    table: str,
    sample_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return total row count and a list of sampled rows for *table*.

    The function queries the adapter for a limited set of rows.  The
    ``adapter.row_count`` method is used to obtain the full row count.
    """
    total_rows = adapter.row_count(table)

    sql = psql.SQL("SELECT * FROM {} LIMIT {}").format(
        psql.Identifier(adapter.schema, table), psql.Literal(sample_size)
    )
    rows = adapter.query(sql)
    return total_rows, rows


def _profile_columns(
    adapter: Any,
    table: str,
    rows: list[dict[str, Any]],
    column_defs: list[tuple[str, str]],
) -> tuple[list[ColumnProfile], list[str]]:
    """Create ``ColumnProfile`` objects for *table* based on *rows*.

    Returns a tuple ``(profiles, candidate_keys)`` where ``candidate_keys``
    holds the names of columns that are unique and non‑null in the sample.
    """
    # Build per‑column collections
    col_values: dict[str, list[Any]] = {name: [] for name, _ in column_defs}
    for row in rows:
        for name, _ in column_defs:
            col_values[name].append(row.get(name))

    profiles: list[ColumnProfile] = []
    candidate_keys: list[str] = []

    for name, data_type in column_defs:
        values = col_values[name]
        total = len(values) or 1  # avoid division by zero
        non_null = [v for v in values if v is not None]
        null_ratio = 1 - (len(non_null) / total)

        # Compute distinct ratio on non‑null values
        distinct = len(set(non_null))
        distinct_ratio = distinct / total if total else 0.0

        # Take up to 5 distinct sample values for inspection
        sample_vals = [str(v) for v in list(dict.fromkeys(non_null))[:5]]

        profile = ColumnProfile(
            name=name,
            data_type=data_type,
            distinct_ratio=distinct_ratio,
            null_ratio=null_ratio,
            samples=sample_vals,
        )
        profiles.append(profile)

        if distinct_ratio == 1.0 and null_ratio == 0.0:
            candidate_keys.append(name)

    return profiles, candidate_keys


def _distinct_non_null_text(
    adapter: Any, table: str, column: str
) -> list[str]:
    """Return a list of distinct, non‑null values for *column* as strings."""
    sql = psql.SQL(
        "SELECT DISTINCT {col}::text AS v FROM {tbl} WHERE {col} IS NOT NULL"
    ).format(col=psql.Identifier(column), tbl=psql.Identifier(adapter.schema, table))
    rows = adapter.query(sql)
    return [row["v"] for row in rows]


def _compute_overlap(
    left_vals: list[str], right_vals_set: set[str]
) -> float:
    """Fraction of *left_vals* that appear in *right_vals_set*."""
    if not left_vals:
        return 0.0
    left_distinct = set(left_vals)
    intersect = left_distinct & right_vals_set
    return len(intersect) / len(left_distinct)


# --------------------------------------------------------------------------- #
# Main discovery function
# --------------------------------------------------------------------------- #


def discover(adapter: Any, sample_size: int = 500) -> SchemaProfile:
    """Discover schema profile for the given read‑only *adapter*.

    The function inspects each table in the adapter, builds column
    statistics, identifies candidate keys, and searches for join
    relationships between tables.

    Parameters
    ----------
    adapter:
        An instance of ``app.adapters.postgres_readonly.ReadOnlyAdapter``.
    sample_size:
        Number of rows to sample per table when computing column
        statistics.  Defaults to ``500``.

    Returns
    -------
    SchemaProfile
        A populated profile describing tables, columns and discovered
        joins.
    """
    schema_name = getattr(adapter, "schema", "")
    tables_profile: dict[str, TableProfile] = {}
    # ------------------------------------------------------------------- #
    # Step 1 – profile each table individually
    # ------------------------------------------------------------------- #
    for table in adapter.list_tables():
        column_defs = adapter.columns(table)  # List[Tuple[name, data_type]]
        total_rows, sample_rows = _sample_table(adapter, table, sample_size)
        col_profiles, candidate_keys = _profile_columns(
            adapter, table, sample_rows, column_defs
        )
        tables_profile[table] = TableProfile(
            name=table,
            row_count=total_rows,
            columns=col_profiles,
            candidate_keys=candidate_keys,
        )

    # ------------------------------------------------------------------- #
    # Step 2 – discover joins
    # ------------------------------------------------------------------- #
    joins: list[Join] = []
    table_names = list(tables_profile.keys())

    # Pre‑fetch distinct values for candidate‑key columns to avoid duplicate queries
    candidate_key_values: dict[tuple[str, str], set[str]] = {}
    for tbl, prof in tables_profile.items():
        for key in prof.candidate_keys:
            distinct_vals = _distinct_non_null_text(adapter, tbl, key)
            candidate_key_values[(tbl, key)] = set(distinct_vals)

    # Iterate over ordered pairs of distinct tables
    for left_tbl in table_names:
        left_prof = tables_profile[left_tbl]
        left_columns = {c.name for c in left_prof.columns}
        for right_tbl in table_names:
            if left_tbl == right_tbl:
                continue
            right_prof = tables_profile[right_tbl]

            # Shared column names where the right column is a candidate key
            shared = left_columns.intersection(right_prof.candidate_keys)
            for col_name in shared:
                # Distinct non‑null values for the left column (as text)
                left_vals = _distinct_non_null_text(adapter, left_tbl, col_name)

                right_vals_set = candidate_key_values.get((right_tbl, col_name), set())
                overlap = _compute_overlap(left_vals, right_vals_set)

                if overlap >= 0.5:
                    joins.append(
                        Join(
                            left_table=left_tbl,
                            left_col=col_name,
                            right_table=right_tbl,
                            right_col=col_name,
                            overlap=overlap,
                        )
                    )

    return SchemaProfile(schema=schema_name, tables=tables_profile, joins=joins)
