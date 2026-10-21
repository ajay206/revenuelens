"""Knowledge connectors for tickets and Confluence pages.

All connectors work against local synthetic exports (no network required) and
expose a small common interface so the reconciliation pipeline can enrich
findings with contextual knowledge.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class KnowledgeItem:
    """A single knowledge item extracted from an external source."""

    source: str  # "jira" | "ado" | "confluence"
    key: str
    title: str
    body: str
    created: str
    labels: list[str]
    url: str


class JiraConnector:
    """Connector over a Jira-style ``tickets.json`` export."""

    def __init__(self, items: list[KnowledgeItem]) -> None:
        self._items = items

    @classmethod
    def from_export(cls, tickets_json_path: str | os.PathLike[str]) -> JiraConnector:
        path = Path(tickets_json_path)
        items: list[KnowledgeItem] = []
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
            for ticket in raw:
                if ticket.get("source") != "jira":
                    continue
                items.append(
                    KnowledgeItem(
                        source="jira",
                        key=ticket.get("key", ""),
                        title=ticket.get("title", ""),
                        body=ticket.get("description", ""),
                        created=ticket.get("created", ""),
                        labels=list(ticket.get("labels", [])),
                        url="https://jira.example.invalid/browse/{}".format(ticket.get("key", "")),
                    )
                )
        return cls(items)

    def items(self) -> list[KnowledgeItem]:
        return list(self._items)

    def search(self, text: str, labels: list[str] | None = None) -> list[KnowledgeItem]:
        keyword = text.lower()
        result: list[KnowledgeItem] = []
        for item in self._items:
            match = (
                keyword in item.title.lower()
                or keyword in item.body.lower()
                or any(keyword in label.lower() for label in item.labels)
            )
            if not match:
                continue
            if labels and not any(label.lower() in [l.lower() for l in item.labels] for label in labels):
                continue
            result.append(item)
        return result


class AdoConnector:
    """Connector over an Azure DevOps-style export."""

    def __init__(self, items: list[KnowledgeItem]) -> None:
        self._items = items

    @classmethod
    def from_export(cls, tickets_json_path: str | os.PathLike[str]) -> AdoConnector:
        path = Path(tickets_json_path)
        items: list[KnowledgeItem] = []
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
            for ticket in raw:
                if ticket.get("source") != "ado":
                    continue
                items.append(
                    KnowledgeItem(
                        source="ado",
                        key=ticket.get("key", ""),
                        title=ticket.get("title", ""),
                        body=ticket.get("description", ""),
                        created=ticket.get("created", ""),
                        labels=list(ticket.get("labels", [])),
                        url="https://dev.azure.example.invalid/nimbus/_workitems/edit/{}".format(
                            ticket.get("key", "")
                        ),
                    )
                )
        return cls(items)

    def items(self) -> list[KnowledgeItem]:
        return list(self._items)

    def search(self, text: str, labels: list[str] | None = None) -> list[KnowledgeItem]:
        keyword = text.lower()
        result: list[KnowledgeItem] = []
        for item in self._items:
            match = (
                keyword in item.title.lower()
                or keyword in item.body.lower()
                or any(keyword in label.lower() for label in item.labels)
            )
            if not match:
                continue
            if labels and not any(label.lower() in [l.lower() for l in item.labels] for label in labels):
                continue
            result.append(item)
        return result


class ConfluenceConnector:
    """Connector over a directory of Markdown pages."""

    def __init__(self, items: list[KnowledgeItem]) -> None:
        self._items = items

    @classmethod
    def from_export(cls, pages_dir: str | os.PathLike[str]) -> ConfluenceConnector:
        root = Path(pages_dir)
        items: list[KnowledgeItem] = []
        if root.exists():
            for md_path in sorted(root.rglob("*.md")):
                content = md_path.read_text(encoding="utf-8")
                title = cls._extract_title(content, md_path.stem)
                items.append(
                    KnowledgeItem(
                        source="confluence",
                        key=md_path.stem,
                        title=title,
                        body=content,
                        created="",
                        labels=[],
                        url=f"https://confluence.example.invalid/pages/{md_path.stem}",
                    )
                )
        return cls(items)

    @staticmethod
    def _extract_title(content: str, fallback: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return fallback

    def items(self) -> list[KnowledgeItem]:
        return list(self._items)

    def search(self, text: str, labels: list[str] | None = None) -> list[KnowledgeItem]:
        keyword = text.lower()
        result: list[KnowledgeItem] = []
        for item in self._items:
            match = (
                keyword in item.title.lower()
                or keyword in item.body.lower()
                or any(keyword in label.lower() for label in item.labels)
            )
            if not match:
                continue
            if labels and not any(label.lower() in [l.lower() for l in item.labels] for label in labels):
                continue
            result.append(item)
        return result


def load_all(export_dir: str | os.PathLike[str]) -> list[KnowledgeItem]:
    """Load knowledge items from ``tickets.json`` and ``pages/*.md`` in *export_dir*."""
    tickets_path = Path(export_dir) / "tickets.json"
    pages_dir = Path(export_dir) / "pages"
    items: list[KnowledgeItem] = []
    if tickets_path.exists():
        jira_conn = JiraConnector.from_export(tickets_path)
        ado_conn = AdoConnector.from_export(tickets_path)
        items.extend(jira_conn.items())
        items.extend(ado_conn.items())
    if pages_dir.exists():
        items.extend(ConfluenceConnector.from_export(pages_dir).items())
    return items


def as_tickets(items: list[KnowledgeItem]) -> list[dict[str, Any]]:
    """Convert :class:`KnowledgeItem` objects into the ticket dict shape expected by :func:`app.explain.match_tickets`."""
    tickets: list[dict[str, Any]] = []
    for item in items:
        tickets.append(
            {
                "key": item.key,
                "source": item.source,
                "title": item.title,
                "description": item.body,
                "labels": list(item.labels),
                "created": item.created,
            }
        )
    return tickets
