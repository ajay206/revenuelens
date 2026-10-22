import os
import re
import time
from typing import Any

import psycopg
import psycopg.errors
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dashboard import render_template
from app.db import company_conn
from app.fixes import log as audit_log
from app.security import create_token, hash_password

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
DEFAULT_ROLE = "viewer"

_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 600.0  # 10 minutes


def registration_enabled() -> bool:
    val = os.getenv("ALLOW_REGISTRATION", "false").strip().lower()
    return val in ("1", "true", "yes", "on")


class RegistrationError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def validate(username: str, password: str, confirm: str | None) -> None:
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise RegistrationError(
            422,
            "Username must be 3–32 characters: letters, digits, dot, underscore or hyphen.",
        )
    if len(password) < 8:
        raise RegistrationError(422, "Password must be at least 8 characters.")
    if confirm is not None and password != confirm:
        raise RegistrationError(422, "Passwords do not match.")


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    timestamps = _rate_limit_store.get(ip, [])
    # Remove expired entries
    while timestamps and now - timestamps[0] > _RATE_LIMIT_WINDOW:
        timestamps.pop(0)
    if len(timestamps) >= _RATE_LIMIT_MAX:
        raise RegistrationError(429, "Too many sign-ups from this address. Try again later.")
    timestamps.append(now)
    _rate_limit_store[ip] = timestamps


def reset_rate_limit() -> None:
    _rate_limit_store.clear()


def register_user(
    username: str,
    password: str,
    confirm: str | None = None,
    client_ip: str = "unknown",
) -> dict[str, Any]:
    if not registration_enabled():
        raise RegistrationError(
            403,
            "Self-registration is turned off for this instance. Ask your admin for an account.",
        )
    validate(username, password, confirm)
    _check_rate_limit(client_ip)

    settings = get_settings()
    tenant_id = settings.company_id
    username = username.strip()

    with company_conn() as conn:
        # Check for existing username or email (case-insensitive)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM app_user
                WHERE tenant_id = %s
                  AND (lower(username) = lower(%s) OR lower(email) = lower(%s))
                """,
                (tenant_id, username, username),
            )
            if cur.fetchone():
                raise RegistrationError(409, "That username is already taken")

        password_hash = hash_password(password)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_user (tenant_id, email, username, password_hash, role)
                    VALUES (%s, NULL, %s, %s, %s)
                    RETURNING id
                    """,
                    (tenant_id, username, password_hash, DEFAULT_ROLE),
                )
                row = cur.fetchone()
                if not row:
                    raise RegistrationError(500, "Failed to create user")
                user_id = row[0]
        except psycopg.errors.UniqueViolation:
            raise RegistrationError(409, "That username is already taken")

        audit_log(
            conn,
            tenant_id,
            username,
            "user_registered",
            f"user:{username}",
            {"role": DEFAULT_ROLE},
        )

    return {"id": str(user_id), "username": username, "role": DEFAULT_ROLE}


class RegisterRequest(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    confirm_password: str | None = None


router = APIRouter()


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def api_register(request: Request, payload: RegisterRequest) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    try:
        result = register_user(
            payload.username, payload.password, payload.confirm_password, client_ip
        )
        return JSONResponse(result, status_code=status.HTTP_201_CREATED)
    except RegistrationError as e:
        return JSONResponse({"detail": e.message}, status_code=e.status_code)


@router.get("/register", response_class=HTMLResponse)
async def register_page() -> HTMLResponse:
    return HTMLResponse(
        render_template(
            "register.html",
            error=None,
            username="",
            enabled=registration_enabled(),
            company_name=get_settings().company_name,
        )
    )


@router.post("/register", response_class=HTMLResponse)
async def register_form(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    confirm_password: str = Form(default=""),
) -> HTMLResponse:
    client_ip = request.client.host if request.client else "unknown"
    settings = get_settings()
    enabled = registration_enabled()
    try:
        result = register_user(username, password, confirm_password, client_ip)
        token = create_token(sub=str(result["id"]), tenant_id=str(settings.company_id))
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            "rl_token",
            token,
            httponly=True,
            samesite="lax",
            secure=not settings.debug if hasattr(settings, "debug") else True,
        )
        return response
    except RegistrationError as e:
        return HTMLResponse(
            render_template(
                "register.html",
                error=e.message,
                username=username,
                enabled=enabled,
                company_name=settings.company_name,
            ),
            status_code=e.status_code,
        )
