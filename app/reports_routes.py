"""API routes for reports and docs generation."""

from __future__ import annotations

import os
import re
import urllib.parse

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.adapters.postgres_readonly import ReadOnlyAdapter
from app.config import get_settings
from app.dashboard import (
    _cache,
    _legacy_schema,
    _legacy_url,
    compute_totals,
    dashboard_user,
    load_findings,
    render_template,
)
from app.discovery import discover
from app.docgen import (
    Doc,
    KnowledgeBase,
    doc_to_dict,
    generate_doc,
    to_markdown,
    to_pdf,
    write_confluence_draft,
)
from app.learning import conflicts, learn_catalog
from app.mapping import map_schema
from legacy_sim.generator import generate

router = APIRouter()


class DocRequest(BaseModel):
    request: str = Field(..., min_length=1)
    level: str = Field(default="analyst")


def load_kb() -> KnowledgeBase:
    """Load knowledge base, cached."""
    if "kb" not in _cache:
        url = _legacy_url()
        schema = _legacy_schema()
        with ReadOnlyAdapter(url, schema) as adapter:
            mapping = map_schema(discover(adapter))
            catalog = learn_catalog(adapter, mapping)
            conflict_list = conflicts(catalog)
        findings = load_findings()
        tickets = generate(seed=42, n_customers=500).tickets
        _cache["kb"] = KnowledgeBase(
            rules=catalog.rules,
            findings=findings,
            tickets=tickets,
            conflicts=conflict_list,
        )
    return _cache["kb"]


# --------------------------------------------------------------------------- #
# Reports endpoints
# --------------------------------------------------------------------------- #


@router.get("/api/reports/findings.csv")
def findings_csv(request: Request):
    dashboard_user(request)
    findings = load_findings()
    from app.reports import findings_to_csv

    csv_content = findings_to_csv(findings)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="revenuelens-findings.csv"'},
    )


@router.get("/api/reports/findings.pdf")
def findings_pdf(request: Request):
    dashboard_user(request)
    findings = load_findings()
    totals = compute_totals(findings)
    settings = get_settings()
    from app.reports import findings_to_pdf

    pdf_bytes = findings_to_pdf(findings, totals, settings.company_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="revenuelens-findings.pdf"'},
    )


# --------------------------------------------------------------------------- #
# Docs endpoints
# --------------------------------------------------------------------------- #


@router.post("/api/docs")
def create_doc(request: Request, body: DocRequest):
    dashboard_user(request)
    if not body.request.strip():
        raise HTTPException(status_code=422, detail="Request cannot be empty")
    if body.level not in ("exec", "analyst", "engineer"):
        raise HTTPException(status_code=422, detail=f"Invalid level: {body.level}")

    kb = load_kb()
    doc = generate_doc(body.request, body.level, kb)
    result = doc_to_dict(doc)
    result["markdown"] = to_markdown(doc)
    return result


@router.get("/api/docs/export")
def export_doc(
    request: Request,
    request_param: str = Query("", alias="request"),
    level: str = Query("analyst"),
    format: str = Query("md"),
):
    dashboard_user(request)
    if not request_param.strip():
        raise HTTPException(status_code=422, detail="Request parameter cannot be empty")
    if level not in ("exec", "analyst", "engineer"):
        raise HTTPException(status_code=422, detail=f"Invalid level: {level}")
    if format not in ("md", "pdf", "confluence"):
        raise HTTPException(status_code=422, detail=f"Invalid format: {format}")

    kb = load_kb()
    doc = generate_doc(request_param, level, kb)

    if format == "md":
        md = to_markdown(doc)
        safe_title = re.sub(r"[^A-Za-z0-9_-]", "-", doc.title)
        return Response(
            content=md,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.md"'},
        )
    elif format == "pdf":
        pdf_bytes = to_pdf(doc)
        safe_title = re.sub(r"[^A-Za-z0-9_-]", "-", doc.title)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.pdf"'},
        )
    else:  # confluence
        drafts_dir = os.getenv("RL_DRAFTS_DIR", "/tmp/revenuelens-drafts")
        file_path = write_confluence_draft(doc, drafts_dir)
        content = file_path.read_bytes()
        return Response(
            content=content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{file_path.name}"',
                "X-Draft-Path": str(file_path),
            },
        )


# --------------------------------------------------------------------------- #
# HTML pages
# --------------------------------------------------------------------------- #


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user = dashboard_user(request)
    settings = get_settings()
    return render_template("reports.html", request=request, user=user, company_name=settings.company_name)


@router.get("/docs", response_class=HTMLResponse)
def docs_page(request: Request):
    user = dashboard_user(request)
    settings = get_settings()

    request_param = request.query_params.get("request", "")
    level = request.query_params.get("level", "analyst")
    doc_html = ""
    export_links = {}

    if request_param:
        if level not in ("exec", "analyst", "engineer"):
            level = "analyst"
        kb = load_kb()
        doc = generate_doc(request_param, level, kb)
        doc_html = _render_doc_html(doc)
        # Build export URLs
        params = urllib.parse.urlencode({"request": request_param, "level": level})
        export_links = {
            "md": f"/api/docs/export?{params}&format=md",
            "pdf": f"/api/docs/export?{params}&format=pdf",
            "confluence": f"/api/docs/export?{params}&format=confluence",
        }

    return render_template(
        "docs.html",
        request=request,
        user=user,
        company_name=settings.company_name,
        request_value=request_param,
        level_value=level,
        doc_html=doc_html,
        export_links=export_links,
    )


def _render_doc_html(doc: Doc) -> str:
    """Render Doc as HTML fragment for embedding in template."""
    parts: list[str] = []
    for section in doc.sections:
        parts.append(f"<h3>{section.heading}</h3>")
        parts.append("<ul>")
        for fact in section.facts:
            conf_class = ' class="needs-confirmation"' if fact.confidence == "needs confirmation" else ""
            conf_badge = '<span class="badge needs-confirmation">needs confirmation</span> ' if fact.confidence == "needs confirmation" else ""
            citations_html = ""
            if fact.citations:
                citations_html = " <em>[" + "; ".join(fact.citations) + "]</em>"
            parts.append(f"<li{conf_class}>{conf_badge}{fact.text}{citations_html}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
