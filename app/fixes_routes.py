from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from .dashboard import (
    dashboard_user,
    load_findings,
    load_stories,
    render_template,
    get_settings,
)
from .db import company_conn
from .fixes import (
    PROPOSED_ACTIONS,
    decide_fix,
    draft_fix,
    get_fix,
    list_audit,
    list_fixes,
    log,
)
from .reconcile import Finding

router = APIRouter()


# ---- Pydantic models for JSON API ----

class DraftRequest(BaseModel):
    leak_id: int


class DecisionRequest(BaseModel):
    approve: bool
    note: str = ""


class DraftResponse(BaseModel):
    id: str
    leak_key: str
    check_name: str
    customer_id: str | None
    amount: str
    title: str
    proposed_action: str
    payload: dict
    status: str
    created_by: str
    decided_by: str | None
    decided_at: str | None
    decision_note: str | None
    created_at: str


class FixListResponse(BaseModel):
    fixes: list[DraftResponse]


class AuditResponse(BaseModel):
    entries: list[dict]


# ---- Helpers ----

def _get_actor(request: Request) -> str:
    """Get current user email from request."""
    user = dashboard_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user["email"]


def _require_auth_html(request: Request) -> str:
    """Get actor for HTML routes, redirect to login if not authenticated."""
    user = dashboard_user(request)
    if not user:
        raise HTTPException(status_code=303, detail="Redirect", headers={"Location": "/login"})
    return user["email"]


def _inr(value: float | str | None) -> str:
    """Format as Indian Rupees."""
    if value is None:
        return "₹0.00"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "₹0.00"
    return f"₹{v:,.2f}"


# ---- HTML Routes ----

@router.post("/leaks/{leak_id:int}/draft", response_class=HTMLResponse)
def create_draft_html(request: Request, leak_id: int):
    """Create a fix draft from a leak (HTML form submission)."""
    actor = _require_auth_html(request)
    findings = load_findings()
    stories = load_stories()

    if leak_id < 0 or leak_id >= len(findings):
        raise HTTPException(status_code=404, detail="Leak not found")

    finding = findings[leak_id]
    story = stories[leak_id]
    tenant_id = str(get_settings().company_id)

    with company_conn() as conn:
        draft_fix(conn, tenant_id, finding, story, actor)

    return RedirectResponse(url="/fixes", status_code=303)


@router.get("/fixes", response_class=HTMLResponse)
def fixes_queue(request: Request, status: str | None = None):
    """HTML page showing the approval queue with tabs by status."""
    actor = _require_auth_html(request)
    settings = get_settings()

    with company_conn() as conn:
        fixes = list_fixes(conn, status)

    return render_template(
        "fixes.html",
        request=request,
        user={"email": actor},
        fixes=fixes,
        current_status=status,
        statuses=["draft", "approved", "rejected"],
        company_name=settings.company_name,
        inr=_inr,
    )


@router.post("/fixes/{fix_id}/approve", response_class=HTMLResponse)
def approve_fix_html(request: Request, fix_id: UUID, note: str = Form(default="")):
    """Approve a fix draft (HTML form)."""
    actor = _require_auth_html(request)

    with company_conn() as conn:
        try:
            decide_fix(conn, fix_id, actor, True, note)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    return RedirectResponse(url="/fixes", status_code=303)


@router.post("/fixes/{fix_id}/reject", response_class=HTMLResponse)
def reject_fix_html(request: Request, fix_id: UUID, note: str = Form(default="")):
    """Reject a fix draft (HTML form)."""
    actor = _require_auth_html(request)

    with company_conn() as conn:
        try:
            decide_fix(conn, fix_id, actor, False, note)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    return RedirectResponse(url="/fixes", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
def audit_log_html(request: Request):
    """HTML page showing audit log."""
    actor = _require_auth_html(request)
    settings = get_settings()

    with company_conn() as conn:
        entries = list_audit(conn)

    return render_template(
        "audit.html",
        request=request,
        user={"email": actor},
        entries=entries,
        company_name=settings.company_name,
    )


# ---- JSON API Routes ----

@router.post("/api/fixes", status_code=201, response_model=DraftResponse)
def create_draft_api(request: Request, payload: DraftRequest):
    """Create a fix draft via JSON API."""
    actor = _get_actor(request)
    findings = load_findings()
    stories = load_stories()

    if payload.leak_id < 0 or payload.leak_id >= len(findings):
        raise HTTPException(status_code=404, detail="Leak not found")

    finding = findings[payload.leak_id]
    story = stories[payload.leak_id]
    tenant_id = str(get_settings().company_id)

    with company_conn() as conn:
        draft = draft_fix(conn, tenant_id, finding, story, actor)

    return _draft_to_response(draft)


@router.get("/api/fixes", response_model=FixListResponse)
def list_fixes_api(request: Request, status: str | None = None):
    """List fix drafts via JSON API."""
    actor = _get_actor(request)

    with company_conn() as conn:
        fixes = list_fixes(conn, status)

    return FixListResponse(fixes=[_draft_to_response(f) for f in fixes])


@router.post("/api/fixes/{fix_id}/decision", response_model=DraftResponse)
def decide_fix_api(request: Request, fix_id: UUID, payload: DecisionRequest):
    """Approve or reject a fix draft via JSON API."""
    actor = _get_actor(request)

    with company_conn() as conn:
        try:
            draft = decide_fix(conn, fix_id, actor, payload.approve, payload.note)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    return _draft_to_response(draft)


@router.get("/api/audit", response_model=AuditResponse)
def audit_log_api(request: Request, limit: int = 200):
    """Get audit log via JSON API."""
    actor = _get_actor(request)

    with company_conn() as conn:
        entries = list_audit(conn, limit)

    return AuditResponse(entries=entries)


def _draft_to_response(draft: dict) -> DraftResponse:
    """Convert DB row to Pydantic response model."""
    return DraftResponse(
        id=str(draft["id"]),
        leak_key=draft["leak_key"],
        check_name=draft["check_name"] or "",
        customer_id=draft["customer_id"] or "",
        amount=str(draft["amount"]) if draft["amount"] is not None else "0.00",
        title=draft["title"] or "",
        proposed_action=draft["proposed_action"] or "",
        payload=draft["payload"] or {},
        status=draft["status"],
        created_by=draft["created_by"] or "",
        decided_by=draft["decided_by"],
        decided_at=draft["decided_at"].isoformat() if draft["decided_at"] else None,
        decision_note=draft["decision_note"],
        created_at=draft["created_at"].isoformat() if draft["created_at"] else "",
    )
