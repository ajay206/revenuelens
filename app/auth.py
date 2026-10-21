from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .db import company_conn
from .security import create_token, decode_token, verify_password

router = APIRouter()


class LoginRequest(BaseModel):
    # Email validation is handled externally; use plain string to avoid email-validator dependency
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    try:
        from .config import get_settings

        settings = get_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    with company_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, password_hash, role
            FROM app_user
            WHERE tenant_id = %s AND email = %s
            """,
            (settings.company_id, payload.email),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        user_id, _, password_hash, _ = row
        if not verify_password(payload.password, password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        token = create_token(sub=str(user_id), tenant_id=settings.company_id)
        return TokenResponse(access_token=token)


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = decode_token(credentials.credentials)
    except jwt.InvalidTokenError:  # pragma: no cover
        # Decode errors are turned into HTTP 401 without original traceback
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from None

    # Retrieve fresh user info
    with company_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT email, role
            FROM app_user
            WHERE id = %s AND tenant_id = %s
            """,
            (payload["sub"], payload["tenant_id"]),
        )
        user = cur.fetchone()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        email, role = user
    return {"email": email, "role": role, "company_id": payload["tenant_id"]}


@router.get("/me")
def me(current_user: Annotated[dict, Depends(get_current_user)]):
    from .config import get_settings

    settings = get_settings()
    return {
        "email": current_user["email"],
        "role": current_user["role"],
        "company_id": current_user["company_id"],
        "company_name": settings.company_name,
    }
