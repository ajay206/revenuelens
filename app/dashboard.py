from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import jwt
from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from app.config import get_settings

from .adapters.postgres_readonly import ReadOnlyAdapter
from .discovery import discover
from .explain import Story
from .mapping import map_schema
from .reconcile import Finding, run_checks
from .security import decode_token

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
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
        "found_total": found_total,
        "month_total": month_total,
        "latest_period": latest_period,
        "count": len(findings),
    }


def inr(value: float) -> str:
    return f"₹{abs(value):,.2f}"


templates.globals["inr"] = inr
templates.globals["abs"] = abs


# --------------------------------------------------------------------------- #
# Additional template helpers
# --------------------------------------------------------------------------- #

def inr_in(value) -> str:
    """
    Format a numeric value using Indian digit grouping and two decimal places,
    prefixed with the rupee symbol. Handles ``None`` and string inputs gracefully.
    """
    if value is None:
        return "₹0.00"
    try:
        num = float(value)
    except (TypeError, ValueError):
        # If it cannot be converted, treat as zero
        num = 0.0
    # Work with absolute value, as the sign is not shown in the formatted output
    num = abs(num)

    # Separate integer and fractional parts
    integer_part, fractional_part = f"{num:.2f}".split(".")
    # Apply Indian grouping: first 3 digits, then groups of 2
    if len(integer_part) > 3:
        # last three digits
        last3 = integer_part[-3:]
        # remaining part, reversed for easier grouping by 2
        rest = integer_part[:-3][::-1]
        groups = [rest[i : i + 2][::-1] for i in range(0, len(rest), 2)]
        integer_part = ",".join(groups[::-1] + [last3])
    return f"₹{integer_part}.{fractional_part}"


def severity(impact) -> str:
    """
    Return a severity label based on the absolute impact value.
    - high   : |impact| >= 1000
    - medium : |impact| >= 100
    - low    : otherwise
    """
    try:
        val = abs(float(impact))
    except (TypeError, ValueError):
        val = 0.0
    if val >= 1000:
        return "high"
    if val >= 100:
        return "medium"
    return "low"


def period_label(p) -> str:
    """
    Convert a period expressed as ``YYYYMM`` (e.g. ``202609``) to a human‑readable
    month‑year string like ``Sep 2026``. Returns ``'No month'`` when ``p`` is falsy.
    """
    if not p:
        return "No month"
    try:
        s = str(p)
        year = int(s[:4])
        month = int(s[4:6])
        # month names list indexed from 1
        month_name = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ][month - 1]
        return f"{month_name} {year}"
    except Exception:  # noqa: BLE001
        return "No month"


templates.globals["inr_in"] = inr_in
templates.filters["inr_in"] = inr_in
templates.globals["severity"] = severity
templates.globals["period_label"] = period_label


# --------------------------------------------------------------------------- #
# Computations for dashboard visualisation
# --------------------------------------------------------------------------- #

def compute_trend(findings: list[Finding]) -> list[dict]:
    """
    Aggregate findings per period (ignoring ``None`` periods) and return a list
    sorted by period (ascending). Each dict contains:
        - period: the raw period identifier
        - label: human readable label via ``period_label``
        - amount: sum of absolute impacts (rounded to 2 decimals)
        - count: number of findings for that period
    """
    period_map: dict[str, dict] = {}
    for f in findings:
        if f.period is None:
            continue
        key = f.period
        entry = period_map.setdefault(
            key,
            {"period": key, "label": period_label(key), "amount": 0.0, "count": 0},
        )
        entry["amount"] += abs(f.impact)
        entry["count"] += 1

    # Convert to list and sort
    result = []
    for key in sorted(period_map):
        entry = period_map[key]
        entry["amount"] = round(entry["amount"], 2)
        result.append(entry)
    return result


def compute_breakdown(findings: list[Finding]) -> list[dict]:
    """
    Aggregate findings per ``check`` (type) and return a list sorted by total
    amount descending. Each dict contains:
        - type: original check identifier
        - label: human‑readable name (underscores replaced with spaces,
                 first letter capitalised)
        - amount: sum of absolute impacts (rounded to 2 decimals)
        - count: number of findings for that type
        - pct: percentage of this amount relative to the maximum amount
    """
    type_map: dict[str, dict] = {}
    for f in findings:
        key = f.check
        entry = type_map.setdefault(
            key,
            {
                "type": key,
                "label": key.replace("_", " ").capitalize(),
                "amount": 0.0,
                "count": 0,
            },
        )
        entry["amount"] += abs(f.impact)
        entry["count"] += 1

    # Determine max amount for percentage calculation
    max_amount = max((e["amount"] for e in type_map.values()), default=0.0)

    # Build final list with rounding and pct
    breakdown = []
    for entry in type_map.values():
        amount = round(entry["amount"], 2)
        pct = (amount / max_amount * 100) if max_amount else 0.0
        breakdown.append(
            {
                "type": entry["type"],
                "label": entry["label"],
                "amount": amount,
                "count": entry["count"],
                "pct": round(pct, 2),
            }
        )
    # Sort by amount descending
    breakdown.sort(key=lambda d: d["amount"], reverse=True)
    return breakdown


# --------------------------------------------------------------------------- #
# Fix statistics helper
# --------------------------------------------------------------------------- #

def fix_stats() -> dict:
    """
    Gather statistics about the fixes stored in the company database.

    Returns a dictionary with:
        - recovered: total amount (float) of approved fixes
        - open: count of fixes with status ``draft``
        - approved: count of fixes with status ``approved``
        - by_key: mapping from ``leak_key`` to the full fix dict
    """
    try:
        # Lazy import to avoid circular dependencies
        from app.db import company_conn
        from app.fixes import list_fixes

        with company_conn() as conn:
            fixes = list_fixes(conn)
    except Exception:  # noqa: BLE001
        return {"recovered": 0.0, "open": 0, "approved": 0, "by_key": {}}

    recovered = 0.0
    open_cnt = 0
    approved_cnt = 0
    by_key: dict[str, dict] = {}

    for fix in fixes:
        status = fix.get("status")
        amount = fix.get("amount", 0)
        try:
            amount_val = float(amount)
        except (TypeError, ValueError):
            amount_val = 0.0

        if status == "approved":
            recovered += amount_val
            approved_cnt += 1
        elif status == "draft":
            open_cnt += 1

        # Build mapping by leak_key
        lk = fix.get("leak_key")
        if lk:
            by_key[lk] = fix

    return {
        "recovered": round(recovered, 2),
        "open": open_cnt,
        "approved": approved_cnt,
        "by_key": by_key,
    }




# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #


def _build_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="bearer", credentials=token)


def _get_token_from_request(request: Request) -> str | None:
    token = request.cookies.get("rl_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


def dashboard_user(request: Request) -> dict:
    token = _get_token_from_request(request)
    if not token:
        if _is_html(request):
            raise HTTPException(status_code=303, detail="Not authenticated", headers={"Location": "/login"})
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decode_token(token)
    except jwt.InvalidTokenError as exc:
        if _is_html(request):
            raise HTTPException(status_code=303, detail="Invalid token", headers={"Location": "/login"})
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    from app.auth import get_current_user  # noqa: WPS433

    credentials = _build_credentials(token)
    return get_current_user(credentials)


def _is_html(request: Request) -> bool:
    return not request.url.path.startswith("/api")


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
        return HTMLResponse(
            content=render_template("login.html", error="Wrong email or password"),
            status_code=401,
        )

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




@router.get("/api/findings")
def api_findings(request: Request, type: str | None = None):
    dashboard_user(request)
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


@router.get("/api/stories")
def api_stories(request: Request, type: str | None = None):
    dashboard_user(request)
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
def api_story(request: Request, story_id: int):
    dashboard_user(request)
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
def api_summary(request: Request):
    dashboard_user(request)
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


# --------------------------------------------------------------------------- #
# Route replacements
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
def home(request: Request, type: str | None = None):
    """
    Render the dashboard home page. All filtered findings are passed to the
    template together with auxiliary data such as trend, breakdown and fix
    statistics.
    """
    user = dashboard_user(request)
    findings = load_findings()

    selected_type = type or ""
    types = sorted({f.check for f in findings})

    if selected_type:
        filtered = [
            (idx, f)
            for idx, f in enumerate(findings)
            if f.check == selected_type
        ]
    else:
        filtered = list(enumerate(findings))

    # Separate indices and objects for the template
    findings_index = [(i, f) for i, f in filtered]
    filtered_findings = [f for _, f in filtered]

    totals = compute_totals(findings)
    settings = get_settings()

    return render_template(
        "home.html",
        request=request,
        user=user,
        findings=filtered_findings,
        findings_index=findings_index,
        totals=totals,
        types=types,
        selected_type=selected_type,
        company_name=settings.company_name,
        trend=compute_trend(findings),
        breakdown=compute_breakdown(findings),
        fixes=fix_stats(),
    )


@router.get("/leaks/{leak_id:int}", response_class=HTMLResponse)
def leak_story(request: Request, leak_id: int):
    """
    Render a single leak story page enriched with fix information,
    severity level and a human‑readable period label.
    """
    user = dashboard_user(request)
    findings = load_findings()
    stories = load_stories()

    if leak_id < 0 or leak_id >= len(findings):
        raise HTTPException(status_code=404, detail="Leak not found")

    finding = findings[leak_id]
    story = stories[leak_id]
    settings = get_settings()

    # Lazy imports to avoid circular dependencies
    from app.fixes import leak_key

    fix = fix_stats()["by_key"].get(leak_key(finding))

    return render_template(
        "story.html",
        request=request,
        user=user,
        finding=finding,
        story=story,
        leak_id=leak_id,
        company_name=settings.company_name,
        fix=fix,
        severity_level=severity(finding.impact),
        period_text=period_label(finding.period),
    )
