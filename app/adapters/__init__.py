"""Database adapter package for RevenueLens."""

from __future__ import annotations

from typing import Union

from .csv_export import CsvExportAdapter
from .postgres_readonly import ReadOnlyAdapter

Adapter = Union[ReadOnlyAdapter, CsvExportAdapter]


def open_source(kind: str, target: str, schema: str = "nimbus") -> Adapter:
    """Factory returning the appropriate adapter for *kind*.

    ``kind`` ``"postgres"`` returns :class:`ReadOnlyAdapter`, while ``"csv"``
    returns :class:`CsvExportAdapter`.
    """
    if kind == "postgres":
        return ReadOnlyAdapter(target, schema)
    if kind == "csv":
        return CsvExportAdapter(target, schema)
    raise ValueError("Unknown adapter kind: {!r}".format(kind))


__all__ = ["ReadOnlyAdapter", "CsvExportAdapter", "open_source", "Adapter"]
