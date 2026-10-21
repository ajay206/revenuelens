"""Documentation generator for RevenueLens.

Deterministic docs-on-demand generator. No LLM required.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpdf import FPDF

from app.learning import Rule
from app.reconcile import Finding
from app.reports import _latin1


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #

@dataclass
class Fact:
    text: str
    citations: list[str] = field(default_factory=list)
    confidence: str = "confirmed"  # "confirmed" or "needs confirmation"


@dataclass
class Section:
    heading: str
    facts: list[Fact] = field(default_factory=list)


@dataclass
class Doc:
    title: str
    request: str
    level: str
    sections: list[Section] = field(default_factory=list)


@dataclass
class KnowledgeBase:
    rules: list[Rule]
    findings: list[Finding]
    tickets: list[dict]
    conflicts: list[dict]


LEVELS = ("exec", "analyst", "engineer")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #

def classify(request: str, known_plans: list[str] = ()) -> tuple[str, str | None]:
    """Classify request into (topic, subject).

    Topics: plan, discount, invoicing, leaks, changes, kt, overview.
    Subject: matched plan id or discount id if found, else None.
    """
    text = request.lower()
    known_plans_lower = [p.lower() for p in known_plans]

    # 1. Plan ID match (case-insensitive)
    for plan in known_plans:
        if plan.lower() in text:
            return "plan", plan

    # 2. Discount ID match (rule keys of kind discount_pct)
    # We don't have rules here, but the caller can pass known_plans? Actually discount IDs are not plans.
    # The spec says: "discount id match (rule keys of kind discount_pct)".
    # Since we don't have rules in classify, we'll rely on the caller to pass known discount IDs via known_plans? No.
    # The spec says: "pass known plan keys via optional arg known_plans". So discount IDs are not passed.
    # However, the test `test_classify_discount` expects topic "discount" and subject None.
    # The test uses `known_plans=["NMB_MAX_699"]` and request "show discount DISC10 details".
    # So we need to detect discount keywords and also if a discount ID pattern appears.
    # But the spec says: "Subject = matched plan id or discount id if found, else None."
    # Since we don't have discount IDs in known_plans, we cannot match them here.
    # The test expects subject None for discount. So we'll just match keywords.

    # Keywords order: kt, changes, discount, plan, invoic/billing, leak/audit, else overview.
    if "kt" in text or "knowledge transfer" in text:
        return "kt", None
    if "change" in text or "history" in text or "what changed" in text:
        return "changes", None
    if "discount" in text:
        # Try to extract a discount ID pattern (e.g., DISC10) but we don't have a list.
        # We'll return None for subject.
        return "discount", None
    if "plan" in text:
        return "plan", None
    if "invoic" in text or "billing" in text:
        return "invoicing", None
    if "leak" in text or "revenue" in text or "audit" in text:
        return "leaks", None
    return "overview", None


# --------------------------------------------------------------------------- #
# Helpers for generate_doc
# --------------------------------------------------------------------------- #

def _rule_citation(rule: Rule) -> str:
    return f"{rule.source} (rule {rule.rule_id})"


def _confidence_str(confidence: float) -> str:
    return "confirmed" if confidence >= 0.95 else "needs confirmation"


def _limit_facts(facts: list[Fact], max_facts: int | None) -> list[Fact]:
    if max_facts is None:
        return facts
    return facts[:max_facts]


def _add_fact_if_citations(facts: list[Fact], text: str, citations: list[str], confidence: str) -> None:
    if not citations:
        confidence = "needs confirmation"
    facts.append(Fact(text=text, citations=citations, confidence=confidence))


def _get_plan_rules(kb: KnowledgeBase, plan_id: str) -> list[Rule]:
    """Return rules relevant to a plan: plan_fee, included_data, overage_rate, usage_rate (keys starting with plan_id), observed_fee."""
    relevant = []
    for rule in kb.rules:
        if rule.kind in ("plan_fee", "included_data", "overage_rate", "observed_fee") and rule.key == plan_id:
            relevant.append(rule)
        elif rule.kind == "usage_rate" and rule.key.startswith(f"{plan_id}:"):
            relevant.append(rule)
    return relevant


def _get_discount_rules(kb: KnowledgeBase, discount_id: str | None = None) -> list[Rule]:
    if discount_id:
        return [r for r in kb.rules if r.kind in ("discount_pct", "discount_window") and r.key == discount_id]
    return [r for r in kb.rules if r.kind in ("discount_pct", "discount_window")]


def _get_tickets_for_plan(kb: KnowledgeBase, plan_id: str) -> list[dict]:
    result = []
    for t in kb.tickets:
        if plan_id in t.get("title", "") or plan_id in t.get("description", "") or "plan" in t.get("labels", []):
            result.append(t)
    return result


def _get_tickets_for_discount(kb: KnowledgeBase) -> list[dict]:
    return [t for t in kb.tickets if "discount" in t.get("labels", [])]


def _get_tickets_for_billing(kb: KnowledgeBase) -> list[dict]:
    return [t for t in kb.tickets if any(l in t.get("labels", []) for l in ("billing", "payment", "rating"))]


def _findings_summary(kb: KnowledgeBase, check: str) -> tuple[int, float, list[str]]:
    """Return (count, total_impact, first_5_record_refs) for a check."""
    relevant = [f for f in kb.findings if f.check == check]
    count = len(relevant)
    total = sum(f.impact for f in relevant)
    refs = []
    for f in relevant[:5]:
        for rid in f.record_ids:
            refs.append(f"{f.table}:{rid}")
            if len(refs) >= 5:
                break
        if len(refs) >= 5:
            break
    return count, total, refs


# --------------------------------------------------------------------------- #
# Generate Doc
# --------------------------------------------------------------------------- #

def generate_doc(request: str, level: str, kb: KnowledgeBase) -> Doc:
    if level not in LEVELS:
        raise ValueError(f"Unknown level: {level}")

    topic, subject = classify(request, known_plans=[r.key for r in kb.rules if r.kind == "plan_fee"])

    # Determine max facts per section
    if level == "exec":
        max_facts = 5
    elif level == "analyst":
        max_facts = 25
    else:  # engineer
        max_facts = None

    sections: list[Section] = []

    # Helper to add a section with limited facts
    def add_section(heading: str, facts: list[Fact]) -> None:
        limited = _limit_facts(facts, max_facts)
        if limited:
            sections.append(Section(heading=heading, facts=limited))

    # ---------------------------
    # Topic: plan
    # ---------------------------
    if topic == "plan":
        plan_ids = [subject] if subject else [r.key for r in kb.rules if r.kind == "plan_fee"]
        for plan_id in plan_ids:
            plan_rules = _get_plan_rules(kb, plan_id)
            facts: list[Fact] = []
            for rule in plan_rules:
                if rule.kind == "plan_fee":
                    text = f"Plan {plan_id} has a monthly fee of INR {rule.value:.2f}."
                elif rule.kind == "included_data":
                    text = f"Plan {plan_id} includes {rule.value:.0f} MB of data."
                elif rule.kind == "overage_rate":
                    text = f"Plan {plan_id} overage rate is INR {rule.value:.4f} per MB."
                elif rule.kind == "usage_rate":
                    # key format: PLAN:TYPE
                    usage_type = rule.key.split(":", 1)[1] if ":" in rule.key else "unknown"
                    text = f"Plan {plan_id} usage rate for {usage_type} is INR {rule.value:.4f} per unit."
                elif rule.kind == "observed_fee":
                    text = f"Observed fee for plan {plan_id} is INR {rule.value:.2f} (from billing)."
                else:
                    continue
                conf = _confidence_str(rule.confidence)
                _add_fact_if_citations(facts, text, [_rule_citation(rule)], conf)

            # Conflicts for this plan
            for conflict in kb.conflicts:
                if conflict.get("plan") == plan_id:
                    text = (f"Config says INR {conflict['config']:.2f} but bills show INR {conflict['observed']:.2f} "
                            f"for plan {plan_id}.")
                    citations = [conflict["source_config"], conflict["source_observed"]]
                    _add_fact_if_citations(facts, text, citations, "needs confirmation")

            # Related tickets
            tickets = _get_tickets_for_plan(kb, plan_id)
            for t in tickets:
                text = f"Ticket {t['key']}: {t['title']}"
                citation = f"{t['source']}:{t['key']}"
                _add_fact_if_citations(facts, text, [citation], "needs confirmation")

            add_section(f"Plan {plan_id}", facts)

    # ---------------------------
    # Topic: discount
    # ---------------------------
    elif topic == "discount":
        discount_rules = _get_discount_rules(kb, subject)
        facts: list[Fact] = []
        for rule in discount_rules:
            if rule.kind == "discount_pct":
                text = f"Discount {rule.key} is {rule.value}%."
            elif rule.kind == "discount_window":
                text = f"Discount {rule.key} is valid from {rule.value}."
            else:
                continue
            conf = _confidence_str(rule.confidence)
            _add_fact_if_citations(facts, text, [_rule_citation(rule)], conf)

        # Tickets labelled discount
        for t in _get_tickets_for_discount(kb):
            text = f"Ticket {t['key']}: {t['title']}"
            citation = f"{t['source']}:{t['key']}"
            _add_fact_if_citations(facts, text, [citation], "needs confirmation")

        # Findings: expired_discount
        count, total, refs = _findings_summary(kb, "expired_discount")
        if count:
            text = f"Expired discount findings: {count} records, total impact INR {abs(total):,.2f}."
            if refs:
                text += f" Sample refs: {', '.join(refs)}."
            _add_fact_if_citations(facts, text, refs, "confirmed" if refs else "needs confirmation")

        add_section("Discounts", facts)

    # ---------------------------
    # Topic: invoicing
    # ---------------------------
    elif topic == "invoicing":
        # Flow section
        flow_facts: list[Fact] = []
        flow_steps = [
            ("Usage data (CDRs) collected from network elements.", "usage"),
            ("Usage rated via rating engine using tariff rules.", "rating"),
            ("Rated usage converted to invoice lines.", "invoice_line"),
            ("Invoice lines aggregated into invoices per customer per period.", "invoice"),
            ("Payments collected and matched to invoices.", "payment"),
        ]
        for desc, table in flow_steps:
            # Find any rule with source containing table
            rule = next((r for r in kb.rules if table in r.source), None)
            if rule:
                citation = _rule_citation(rule)
                conf = _confidence_str(rule.confidence)
            else:
                citation = "inferred:schema mapping"
                conf = "needs confirmation"
            _add_fact_if_citations(flow_facts, desc, [citation], conf)
        add_section("Invoicing Flow", flow_facts)

        # Findings summary per check
        finding_facts: list[Fact] = []
        for check in ("rated_not_invoiced", "duplicate_charge", "unmatched_payment", "unrated_usage"):
            count, total, refs = _findings_summary(kb, check)
            if count:
                text = f"{check}: {count} findings, total INR {abs(total):,.2f} impact."
                if refs:
                    text += f" Sample refs: {', '.join(refs)}."
                _add_fact_if_citations(finding_facts, text, refs, "confirmed" if refs else "needs confirmation")
        add_section("Findings Summary", finding_facts)

        # Tickets labelled billing/payment/rating
        ticket_facts: list[Fact] = []
        for t in _get_tickets_for_billing(kb):
            text = f"Ticket {t['key']}: {t['title']}"
            citation = f"{t['source']}:{t['key']}"
            _add_fact_if_citations(ticket_facts, text, [citation], "needs confirmation")
        add_section("Related Tickets", ticket_facts)

    # ---------------------------
    # Topic: leaks
    # ---------------------------
    elif topic == "leaks":
        facts: list[Fact] = []
        for check in ("expired_discount", "rated_not_invoiced", "duplicate_charge", "unmatched_payment", "unrated_usage"):
            count, total, refs = _findings_summary(kb, check)
            if count:
                text = f"{check}: {count} records, total INR {abs(total):,.2f} impact."
                if refs:
                    text += f" Refs: {', '.join(refs[:3])}."
                _add_fact_if_citations(facts, text, refs[:3], "confirmed" if refs else "needs confirmation")
        add_section("Revenue Leaks", facts)

    # ---------------------------
    # Topic: changes
    # ---------------------------
    elif topic == "changes":
        facts: list[Fact] = []
        sorted_tickets = sorted(kb.tickets, key=lambda t: t.get("created", ""), reverse=True)
        for t in sorted_tickets:
            date = t.get("created", "")[:10]
            text = f"On {date}: {t['title']}"
            citation = f"{t['source']}:{t['key']}"
            _add_fact_if_citations(facts, text, [citation], "needs confirmation")
        add_section("Recent Changes", facts)

    # ---------------------------
    # Topic: kt
    # ---------------------------
    elif topic == "kt":
        # Intro section
        intro_facts = [
            Fact(
                text="This document provides a knowledge transfer overview of RevenueLens configuration, invoicing flow, and plans.",
                citations=[],
                confidence="needs confirmation"
            ),
            Fact(
                text="Use the table of contents to navigate. Each fact includes citations; items marked '(needs confirmation)' require verification.",
                citations=[],
                confidence="needs confirmation"
            ),
        ]
        add_section("How to use this document", intro_facts)

        # Then include overview, invoicing, and all plans
        # Overview
        overview_facts: list[Fact] = []
        kind_counts: dict[str, int] = {}
        for r in kb.rules:
            kind_counts[r.kind] = kind_counts.get(r.kind, 0) + 1
        for kind, cnt in sorted(kind_counts.items()):
            _add_fact_if_citations(overview_facts, f"Rule kind '{kind}': {cnt} rules.", [], "confirmed")
        plan_ids = sorted({r.key for r in kb.rules if r.kind == "plan_fee"})
        _add_fact_if_citations(overview_facts, f"Number of plans: {len(plan_ids)}.", [], "confirmed")
        _add_fact_if_citations(overview_facts, f"Total findings: {len(kb.findings)}.", [], "confirmed")
        add_section("Overview", overview_facts)

        # Invoicing (reuse invoicing topic logic but without tickets? We'll just call generate_doc for invoicing and merge sections? Simpler: replicate minimal invoicing flow and findings)
        # We'll create a mini invoicing section.
        flow_facts: list[Fact] = []
        flow_steps = [
            ("Usage data (CDRs) collected from network elements.", "usage"),
            ("Usage rated via rating engine using tariff rules.", "rating"),
            ("Rated usage converted to invoice lines.", "invoice_line"),
            ("Invoice lines aggregated into invoices per customer per period.", "invoice"),
            ("Payments collected and matched to invoices.", "payment"),
        ]
        for desc, table in flow_steps:
            rule = next((r for r in kb.rules if table in r.source), None)
            if rule:
                citation = _rule_citation(rule)
                conf = _confidence_str(rule.confidence)
            else:
                citation = "inferred:schema mapping"
                conf = "needs confirmation"
            _add_fact_if_citations(flow_facts, desc, [citation], conf)
        add_section("Invoicing Flow", flow_facts)

        # All plans
        for plan_id in plan_ids:
            plan_rules = _get_plan_rules(kb, plan_id)
            facts: list[Fact] = []
            for rule in plan_rules:
                if rule.kind == "plan_fee":
                    text = f"Plan {plan_id} has a monthly fee of INR {rule.value:.2f}."
                elif rule.kind == "included_data":
                    text = f"Plan {plan_id} includes {rule.value:.0f} MB of data."
                elif rule.kind == "overage_rate":
                    text = f"Plan {plan_id} overage rate is INR {rule.value:.4f} per MB."
                elif rule.kind == "usage_rate":
                    usage_type = rule.key.split(":", 1)[1] if ":" in rule.key else "unknown"
                    text = f"Plan {plan_id} usage rate for {usage_type} is INR {rule.value:.4f} per unit."
                elif rule.kind == "observed_fee":
                    text = f"Observed fee for plan {plan_id} is INR {rule.value:.2f} (from billing)."
                else:
                    continue
                conf = _confidence_str(rule.confidence)
                _add_fact_if_citations(facts, text, [_rule_citation(rule)], conf)
            add_section(f"Plan {plan_id}", facts)

    # ---------------------------
    # Topic: overview
    # ---------------------------
    else:  # overview
        facts: list[Fact] = []
        kind_counts: dict[str, int] = {}
        for r in kb.rules:
            kind_counts[r.kind] = kind_counts.get(r.kind, 0) + 1
        for kind, cnt in sorted(kind_counts.items()):
            _add_fact_if_citations(facts, f"Rule kind '{kind}': {cnt} rules.", [], "confirmed")
        plan_ids = sorted({r.key for r in kb.rules if r.kind == "plan_fee"})
        _add_fact_if_citations(facts, f"Number of plans: {len(plan_ids)}.", [], "confirmed")
        _add_fact_if_citations(facts, f"Total findings: {len(kb.findings)}.", [], "confirmed")
        _add_fact_if_citations(facts, f"Total conflicts: {len(kb.conflicts)}.", [], "confirmed")
        add_section("Overview", facts)

    # ---------------------------
    # Level-specific additions
    # ---------------------------
    if level == "exec":
        # Add Summary section at the beginning
        total_leak_inr = sum(abs(f.impact) for f in kb.findings)
        summary_facts = [
            Fact(text=f"Total leak INR impact: {total_leak_inr:,.2f}.", citations=[], confidence="needs confirmation"),
            Fact(text=f"Number of rules: {len(kb.rules)}.", citations=[], confidence="needs confirmation"),
            Fact(text=f"Number of conflicts: {len(kb.conflicts)}.", citations=[], confidence="needs confirmation"),
        ]
        sections.insert(0, Section(heading="Summary", facts=summary_facts))

    if level == "engineer":
        # Add Data Sources section at the end
        source_tables = sorted({r.source.split(":")[0] for r in kb.rules})
        facts = [Fact(text=f"Source table: {src}", citations=[src], confidence="confirmed") for src in source_tables]
        add_section("Data Sources", facts)

    # Ensure any fact without citations has confidence "needs confirmation"
    for section in sections:
        for fact in section.facts:
            if not fact.citations and fact.confidence != "needs confirmation":
                fact.confidence = "needs confirmation"

    title = f"RevenueLens Doc: {topic.title()}"
    if subject:
        title += f" - {subject}"
    return Doc(title=title, request=request, level=level, sections=sections)


# --------------------------------------------------------------------------- #
# Output formats
# --------------------------------------------------------------------------- #

def to_markdown(doc: Doc) -> str:
    lines = [f"# {doc.title}", f"_Level: {doc.level} · Request: \"{doc.request}\"_", ""]
    footnotes: list[list[str]] = []  # per fact
    footnote_counter = 0

    for section in doc.sections:
        lines.append(f"## {section.heading}")
        for fact in section.facts:
            footnote_counter += 1
            ref = f"[^{footnote_counter}]"
            conf_marker = " **(needs confirmation)**" if fact.confidence == "needs confirmation" else ""
            lines.append(f"- {fact.text}{conf_marker} {ref}")
            footnotes.append(fact.citations)
        lines.append("")

    if footnotes:
        lines.append("## Sources")
        for i, citations in enumerate(footnotes, 1):
            if citations:
                lines.append(f"[^{i}]: {'; '.join(citations)}")
            else:
                lines.append(f"[^{i}]: (no citation)")

    return "\n".join(lines)


def to_pdf(doc: Doc) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin1(doc.title), ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _latin1(f"Level: {doc.level} · Request: {doc.request}"), ln=True)
    pdf.ln(6)

    for section in doc.sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, _latin1(section.heading))
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 10)
        for fact in section.facts:
            text = fact.text
            if fact.confidence == "needs confirmation":
                text += " (needs confirmation)"
            if fact.citations:
                text += " [" + "; ".join(fact.citations) + "]"
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 6, _latin1(text))
            pdf.ln(1)
        pdf.ln(4)

    return bytes(pdf.output())


def to_confluence_storage(doc: Doc) -> str:
    parts = []
    # Info macro
    parts.append('<ac:structured-macro ac:name="info"><ac:rich-text-body>')
    parts.append('<p>DRAFT generated by RevenueLens – review before publishing</p>')
    parts.append('</ac:rich-text-body></ac:structured-macro>')

    # Title
    parts.append(f"<h1>{html.escape(doc.title)}</h1>")
    parts.append(f"<p><em>Level: {html.escape(doc.level)} · Request: {html.escape(doc.request)}</em></p>")

    for section in doc.sections:
        parts.append(f"<h2>{html.escape(section.heading)}</h2>")
        parts.append("<ul>")
        for fact in section.facts:
            conf_marker = " <em>(needs confirmation)</em>" if fact.confidence == "needs confirmation" else ""
            citations_html = ""
            if fact.citations:
                citations_html = " <em>[" + "; ".join(html.escape(c) for c in fact.citations) + "]</em>"
            text = html.escape(fact.text)
            parts.append(f"<li>{text}{conf_marker}{citations_html}</li>")
        parts.append("</ul>")

    return "\n".join(parts)


def write_confluence_draft(doc: Doc, out_dir: str | Path) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", doc.title)
    file_path = out_path / f"{slug}.confluence.xml"
    content = to_confluence_storage(doc)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def doc_to_dict(doc: Doc) -> dict[str, Any]:
    return {
        "title": doc.title,
        "request": doc.request,
        "level": doc.level,
        "sections": [
            {
                "heading": s.heading,
                "facts": [
                    {
                        "text": f.text,
                        "citations": f.citations,
                        "confidence": f.confidence,
                    }
                    for f in s.facts
                ],
            }
            for s in doc.sections
        ],
    }
