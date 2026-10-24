"""Error handling utilities for RevenueLens.

Provides HTML and JSON responses for HTTP and validation errors,
including special handling for API routes, authentication redirects,
and user‑friendly error pages.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings

# The dashboard module contains the Jinja2 rendering helper.
# pylint: disable=import-error
from app.dashboard import dashboard_user, render_template


def _is_api_path(path: str) -> bool:
    """Return True if the request should be treated as an API call."""
    return path.startswith(("/api", "/auth"))


def _json_error_response(
    exc: StarletteHTTPException | RequestValidationError,
    request: Request,
) -> JSONResponse:
    """Create a JSONResponse for API errors."""
    if isinstance(exc, StarletteHTTPException):
        payload = {"detail": exc.detail}
        status_code = exc.status_code
        headers = getattr(exc, "headers", None)
    else:  # RequestValidationError
        payload = {"detail": jsonable_encoder(exc.errors())}
        status_code = 422
        headers = None
    return JSONResponse(payload, status_code=status_code, headers=headers)


def _html_error_context(
    request: Request,
    exc: StarletteHTTPException,
) -> dict[str, Any]:
    """Build the context dictionary used for rendering the error page."""
    # Default messages
    heading = "Something went wrong"
    message = "Please try again in a moment."

    if exc.status_code == 401:
        # HTML pages should redirect to login; the caller handles that.
        heading = "Please sign in"
        message = "Your session has ended. Sign in to continue."
    elif exc.status_code == 403:
        heading = "You don't have access to this"
        # Use custom detail when provided.
        if isinstance(exc.detail, str) and exc.detail != "Forbidden":
            message = exc.detail
        else:
            message = (
                "Your role can view this workspace but can't make this change. "
                "Ask an admin or analyst."
            )
    elif exc.status_code == 404:
        heading = "Page not found"
        message = (
            "We couldn't find that page. It may have moved, or the link is out of date."
        )
    elif exc.status_code == 409:
        heading = "That change can't be made"
        message = str(exc.detail)
    elif exc.status_code == 422:
        heading = "Something in that request wasn't valid"
        message = "Please go back and check the form."

    # Retrieve the current user for the top‑bar if possible.
    try:
        user = dashboard_user(request)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        user = None

    # Retrieve the company name from settings.
    try:
        settings = get_settings()
        company_name = getattr(settings, "company_name", None)
    except Exception:  # noqa: BLE001
        company_name = None

    return {
        "request": request,
        "user": user,
        "company_name": company_name,
        "status_code": exc.status_code,
        "heading": heading,
        "message": message,
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register HTTP and validation error handlers on the given FastAPI app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse | HTMLResponse | RedirectResponse:
        """Handle generic HTTP exceptions."""
        path = request.url.path

        # API / auth routes – always JSON (including redirects).
        if _is_api_path(path) or "text/html" not in request.headers.get("accept", ""):
            # For 3xx redirects that include a Location header, return a proper
            # RedirectResponse instead of JSON.
            if 300 <= exc.status_code < 400 and getattr(exc, "headers", None):
                location = exc.headers.get("Location")
                if location:
                    return RedirectResponse(location, status_code=exc.status_code)
            return _json_error_response(exc, request)

        # Non‑API routes.
        # 3xx redirects (e.g., dashboard_user raising a redirect) should be sent
        # as an actual HTTP redirect.
        if 300 <= exc.status_code < 400 and getattr(exc, "headers", None):
            location = exc.headers.get("Location")
            if location:
                return RedirectResponse(location, status_code=exc.status_code)

        # 401 on HTML pages – redirect to login page.
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)

        # Render a friendly error page for all other statuses.
        context = _html_error_context(request, exc)
        html = render_template("error.html", **context)
        return HTMLResponse(content=html, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse | HTMLResponse:
        """Handle request validation errors."""
        if _is_api_path(request.url.path) or "text/html" not in request.headers.get("accept", ""):
            return _json_error_response(exc, request)

        # For regular HTML routes render the same error page but with a 422 status.
        # Re‑use the HTML context logic, passing a synthetic HTTPException.
        fake_http_exc = StarletteHTTPException(status_code=422, detail="Unprocessable Entity")
        context = _html_error_context(request, fake_http_exc)
        html = render_template("error.html", **context)
        return HTMLResponse(content=html, status_code=422)

    # Ensure the function returns nothing (FastAPI expects side‑effects only).
