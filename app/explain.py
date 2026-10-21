"""Step 5 – Explain findings with an AI agent.

This module builds deterministic story objects from the reconciliation findings,
matches them to recent tickets, and asks a language model for a natural‑language
explanation.  Money impact and citations are *always* computed locally – the LLM
only provides the narrative fields.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.postgres_readonly import ReadOnlyAdapter
from app.discovery import discover
from app.llm import LLM, free_llm_from_env, parse_json
from app.mapping import map_schema
from app.reconcile import Finding, run_checks
from legacy_sim.generator import generate  # type: ignore[import]

# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Story:
    """Structured explanation of a revenue leak."""

    check: str
    customer_id: str | None
    title: str
    what: str
    since_when: str
    root_cause: str
    money_impact: float  # INR, positive = revenue lost
    who_affected: str
    what_to_do: str
    citations: list[dict] = field(default_factory=list)  # {"type": "...", "ref": "..."}
    confidence: str = "needs confirmation"  # "high" or "needs confirmation"


# ---------------------------------------------------------------------------
# Ticket matching utilities
# ---------------------------------------------------------------------------

_CHECK_TO_TICKET_KEY: Mapping[str, str] = {
    "unrated_usage": "rating",
    "rated_not_invoiced": "billing",
    "tariff_mismatch": "tariff",
    "expired_discount": "discount/expiry",
    "provisioned_not_billed": "provisioning",
    "missed_renewal": "renewal",
    "unmatched_payment": "payment",
    "duplicate_charge": "duplicate",
}


def match_tickets(finding: Finding, tickets: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Return up to three tickets whose label or title matches the check.

    The mapping in ``_CHECK_TO_TICKET_KEY`` defines a keyword for each check.
    Matching is case‑insensitive and looks for the keyword in either the ticket
    ``labels`` list or the ticket ``title``.
    """
    keyword = _CHECK_TO_TICKET_KEY.get(finding.check, "")
    if not keyword:
        return []

    matched: list[dict] = []
    lowered = keyword.lower()
    for ticket in tickets:
        # Normalise ticket fields
        title = str(ticket.get("title", "")).lower()
        labels = [str(l).lower() for l in ticket.get("labels", [])]

        if lowered in title or lowered in labels:
            matched.append(ticket)
            if len(matched) >= 3:
                break
    return matched


# ---------------------------------------------------------------------------
# Prompt construction & LLM handling
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert revenue‑operations analyst. Summarise the given finding in "
    "clear, concise language. Respond ONLY with a JSON object containing the "
    "keys: title, what, since_when, root_cause, who_affected, what_to_do."
)


def _build_user_prompt(finding: Finding, ticket_matches: Sequence[Mapping[str, Any]]) -> str:
    """Create the user part of the prompt with all deterministic data."""
    base = {
        "check": finding.check,
        "record_ids": finding.record_ids,
        "table": finding.table,
        "customer_id": finding.customer_id,
        "period": finding.period,
        "impact": finding.impact,
        "evidence": finding.evidence,
        "description": finding.description,
        "matched_tickets": [
            {"key": t.get("key"), "title": t.get("title"), "labels": t.get("labels")} for t in ticket_matches
        ],
    }
    return json.dumps(base, indent=2, ensure_ascii=False)


def explain_finding(finding: Finding, tickets: Sequence[Mapping[str, Any]], llm: LLM) -> Story:
    """Create a Story for a single finding."""
    # 1️⃣ Deterministic calculations
    money_impact = round(abs(finding.impact), 2)

    # citations for each record id
    citations: list[dict] = [
        {"type": "record", "ref": f"{finding.table}:{rid}"} for rid in finding.record_ids
    ]

    # 2️⃣ Ticket matching (deterministic)
    matched = match_tickets(finding, tickets)
    for t in matched:
        citations.append({"type": "ticket", "ref": t.get("key", "UNKNOWN")})

    # 3️⃣ Ask the LLM for the narrative fields
    user_prompt = _build_user_prompt(finding, matched)
    raw_response = llm.complete(_SYSTEM_PROMPT, user_prompt)
    parsed = parse_json(raw_response)

    # 4️⃣ Extract fields with fall‑backs
    def _field(name: str, fallback: str) -> str:
        val = parsed.get(name)
        if isinstance(val, str) and val.strip():
            return val.strip()
        # deterministic fallback based on finding attributes
        templates = {
            "title": f"{finding.check.replace('_', ' ').title()} detected",
            "what": finding.description or "No description provided.",
            "since_when": finding.period or "Unknown period",
            "root_cause": "Root cause not identified by AI.",
            "who_affected": "Customers affected: unknown.",
            "what_to_do": "Investigation required.",
        }
        return templates.get(name, fallback)

    title = _field("title", "")
    what = _field("what", "")
    since_when = _field("since_when", finding.period or "")
    root_cause = _field("root_cause", "")
    who_affected = _field("who_affected", "")
    what_to_do = _field("what_to_do", "")

    confidence = "high"
    # if any field came from the fallback template we downgrade confidence
    if any(
        parsed.get(k) in (None, "", []) for k in ("title", "what", "since_when", "root_cause", "who_affected", "what_to_do")
    ):
        confidence = "needs confirmation"

    return Story(
        check=finding.check,
        customer_id=finding.customer_id,
        title=title,
        what=what,
        since_when=since_when,
        root_cause=root_cause,
        money_impact=money_impact,
        who_affected=who_affected,
        what_to_do=what_to_do,
        citations=citations,
        confidence=confidence,
    )


def explain_all(
    findings: Sequence[Finding],
    tickets: Sequence[Mapping[str, Any]],
    llm: LLM,
    limit: int | None = None,
) -> list[Story]:
    """Explain a collection of findings, optionally limiting the number processed."""
    stories: list[Story] = []
    for idx, f in enumerate(findings):
        if limit is not None and idx >= limit:
            break
        stories.append(explain_finding(f, tickets, llm))
    return stories


# ---------------------------------------------------------------------------
# Rendering utilities
# ---------------------------------------------------------------------------

def to_markdown(stories: Sequence[Story]) -> str:
    """Render a list of stories as markdown."""
    lines: list[str] = []
    for s in stories:
        lines.append(f"## {s.title}")
        lines.append("")
        lines.append(f"**Check**: {s.check}")
        lines.append(f"**Customer**: {s.customer_id or 'N/A'}")
        lines.append(f"**Impact (INR)**: {s.money_impact}")
        lines.append(f"**Since**: {s.since_when}")
        lines.append("")
        lines.append(f"**What**: {s.what}")
        lines.append("")
        lines.append(f"**Root cause**: {s.root_cause}")
        lines.append("")
        lines.append(f"**Who is affected**: {s.who_affected}")
        lines.append("")
        lines.append(f"**What to do**: {s.what_to_do}")
        lines.append("")
        lines.append("**Confidence**: " + s.confidence)
        lines.append("")
        lines.append("**Sources**:")
        for c in s.citations:
            lines.append(f"- {c['type'].title()}: {c['ref']}")
        lines.append("\n---\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _load_tickets() -> list[dict]:
    """Generate a deterministic set of tickets from the legacy simulator."""
    # The simulator returns an object with a ``tickets`` attribute.
    sim = generate(seed=42, n_customers=500)  # type: ignore[arg-type]
    return getattr(sim, "tickets", [])


def main(argv: list[str] | None = None) -> None:
    """CLI for step 5.

    Usage:
        python -m app.explain --database-url URL --schema nimbus --out stories.md [--limit N]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Explain reconciliation findings.")
    parser.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--schema", required=True, help="Database schema name")
    parser.add_argument("--out", required=True, help="Path to output markdown file")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of findings to explain")
    args = parser.parse_args(argv)

    # 1️⃣ Discover schema & run checks
    with ReadOnlyAdapter(args.database_url, args.schema) as adapter:
        mapping = map_schema(discover(adapter))
        findings = run_checks(adapter, mapping)

    # 2️⃣ Load tickets & LLM
    tickets = _load_tickets()
    llm = free_llm_from_env()

    # 3️⃣ Explain & render
    stories = explain_all(findings, tickets, llm, limit=args.limit)
    md = to_markdown(stories)

    out_path = Path(args.out)
    out_path.write_text(md, encoding="utf-8")

    # also write a JSON representation for downstream tools
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps([asdict(s) for s in stories], ensure_ascii=False, indent=2))

    print(f"Wrote {len(stories)} stories to {out_path} (markdown) and {json_path} (JSON).", file=sys.stderr)


if __name__ == "__main__":
    main()
