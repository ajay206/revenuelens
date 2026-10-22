from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.answer_key import build_report
from app.dashboard import dashboard_user, render_template
from app.db import company_conn

router = APIRouter()


@router.get("/api/answer-key")
def api_answer_key(request: Request):
    dashboard_user(request)
    with company_conn() as conn:
        report = build_report(conn)
    return report


@router.get("/planted", response_class=HTMLResponse)
def planted_page(request: Request):
    user = dashboard_user(request)
    with company_conn() as conn:
        report = build_report(conn)
    from app.config import get_settings

    settings = get_settings()
    return HTMLResponse(render_template(
        "planted.html",
        request=request,
        user=user,
        company_name=settings.company_name,
        path="/planted",
        report=report,
    ))
