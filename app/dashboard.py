from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from .db import ReadOnlyAdapter
from .explain import Story
from .findings import Finding, discover, run_checks
from .schema import map_schema
from .security import decode_token
from config import get_settings

router = APIRouter()

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(name: str, **context: Any) -> str:
    return templates.get_template(name).render(**context)


class LoginForm(BaseModel):
    email: str
    password: str


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #

_cache: dict[str, Any] = {}


def reset_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #


def _legacy_url() -> str:
    return os.getenv("LEGACY_DATABASE_URL", os.getenv("DATABASE_URL", ""))


def _legacy_schema() -> str:
    return os.getenv("LEGACY_SCHEMA", "nimbus")


def load_findings() -> list[Finding]:
    if "findings" not in _cache:
        url = _legacy_url()
        schema = _legacy_schema()
        findings: list[Finding] = []
        with ReadOnlyAdapter(url, schema) as a:
            findings = list(run_checks(a, map_schema(discover(a))))
        findings.sort(key=lambda f: abs(f.impact), reverse=True)
        _cache["findings"] = findings
    return _cache["findings"]


def load_stories() -> list[Story]:
    if "stories" not in _cache:
        from app.explain import explain_all
        from app.llm import free_llm_from_env
        from legacy_sim.generator import generate

        tickets = generate(seed=42, n_customers=500).tickets
        llm = free_llm_from_env()
        findings = load_findings()
        _cache["stories"] = list(explain_all(findings, tickets, llm))
    return _cache["stories"]


# --------------------------------------------------------------------------- #
# Totals
# --------------------------------------------------------------------------- #


def compute_totals(findings: list[Finding]) -> dict[str, Any]:
    found_total = round(sum(abs(f.impact) for f in findings), 2)
    periods = sorted(p for f in findings if (p := f.period))
    latest_period = periods[-1] if periods else None
    if latest_period:
        month_total = round(
            sum(abs(f.impact) for f in findings if f.period == latest_period), 2
        )
    else:
        month_total = found_total
    return {
        "month_total": month_total,
        "found_total": found_total,
        "latest_period": latest_period,
        "count": len(findings),
    }


def inr(value: float) -> str:
    return f"₹{abs(value):,.2f}"


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #


def _build_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="bearer", credentials=token)


def dashboard_user(request: Request) -> dict:
    token = request.cookies.get("rl_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        from app.auth import get_current_user  # noqa: WPS433

        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    # Verify user exists by reusing the same logic as app.auth.get_current_user
    from app.auth import get_current_user  # noqa: WPS433

    credentials = _build_credentials(token)
    return get_current_user(credentials)


def _is_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render_template("login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    from app.auth import LoginRequest, login

    try:
        result = login(LoginRequest(email=email, password=password))
        token = result.access_token
    except HTTPException:
        return render_template("login.html", error="Wrong email or password"), 401

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "rl_token",
        token,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout", response_class=HTMLResponse)
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("rl_token")
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request, type: str | None = None):
    user = dashboard_user(request)
    findings = load_findings()

    selected_type = type or ""
    types = sorted({f.check for f in findings})

    if selected_type:
        filtered = [f for f in findings if f.check == selected_type]
    else:
        filtered = findings

    top = filtered[:20]
    totals = compute_totals(findings)
    totals = compute_totals(findings)
    settings = get_settings()

    return render_template(
        "home.html",
        request=request,
        user=user,
        findings=top,
        totals=totals,
        types=types,
        selected_type=selected_type,
        company_name=settings.company_name,
    )


@router.get("/leaks/{leak_id:int}", response_class=HTMLResponse)
def leak_story(request: Request, leak_id: int):
    if _is_html(request):
        user = dashboard_user(request)
    else:
        user = True  # api path doesn't require auth

    findings = load_findings()
    stories = load_stories()

    if leak_id < 0 or leak_id >= len(findings):
        raise HTTPException(status_code=404, detail="Leak not found")

    finding = findings[leak_id]
    story = stories[leak_id]
    settings = get_settings()

    return render_template(
        "story.html",
        request=request,
        user=user,
        finding=finding,
        story=story,
        company_name=settings.company_name,
    )


@router.get("/api/findings")
def api_findings(type: str | None = None):
    dashboard_user_from_request(None)
    findings = load_findings()
    if type:
        findings = [f for f in findings if f.check == type]
    return [
        {
            "id": i,
            "check": f.check,
            "customer_id": f.customer_id,
            "period": f.period,
            "impact": f.impact,
            "money": abs(f.impact),
            "record_ids": f.record_ids,
            "table": f.table,
            "description": f.description,
        }
        for i, f in enumerate(findings)
    ]


def dashboard_user_from_request(request: Request | None) -> dict:
    """Wrapper used by API routes to enforce auth."""
    from fastapi import Depends

    return Depends(dashboard_user)


@router.get("/api/stories")
def api_stories(type: str | None = None):
    _require_auth()
    stories = load_stories()
    if type:
        stories = [s for s in stories if s.check == type]
    return [
        {
            "id": i,
            "check": s.check,
            "customer_id": s.customer_id,
            "title": s.title,
            "what": s.what,
            "since_when": s.since_when,
            "root_cause": s.root_cause,
            "money_impact": s.money_impact,
            "who_affected": s.who_affected,
            "what_to_do": s.what_to_do,
            "citations": s.citations,
            "confidence": s.confidence,
        }
        for i, s in enumerate(stories)
    ]


@router.get("/api/stories/{story_id:int}")
def api_story(story_id: int):
    _require_auth()
    stories = load_stories()
    if story_id < 0 or story_id >= len(stories):
        raise HTTPException(status_code=404, detail="Story not found")
    s = stories[story_id]
    return {
        "id": story_id,
        "check": s.check,
        "customer_id": s.customer_id,
        "title": s.title,
        "what": s.what,
        "since_when": s.since_when,
        "root_cause": s.root_cause,
        "money_impact": s.money_impact,
        "who_affected": s.who_affected,
        "what_to_do": s.what_to_do,
        "citations": s.citations,
        "confidence": s.confidence,
    }


@router.get("/api/summary")
def api_summary():
    _require_auth()
    findings = load_findings()
    totals = compute_totals(findings)
    per_type_money: dict[str, float] = {}
    per_type_count: dict[str, int] = {}
    for f in findings:
        per_type_money[f.check] = round(per_type_money.get(f.check, 0) + abs(f.impact), 2)
        per_type_count[f.check] = per_type_count.get(f.check, 0) + 1
    totals["per_type"] = {
        t: {"total": per_type_money[t], "count": per_type_count[t]}
        for t in sorted(per_type_money)
    }
    return totals


def _require_auth() -> None:
    """Raise 401 unconditionally for API-only calls not routed through dashboard_user."""
    raise HTTPException(status_code=401, detail="Not authenticated")
</arg_value>
