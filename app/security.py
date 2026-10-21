import datetime
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

from .config import get_settings


def hash_password(password: str) -> str:
    """Hash a plain password using bcrypt and return the encoded hash."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _make_claims(sub: str, tenant_id: str) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.datetime.now(datetime.UTC)
    exp = now + datetime.timedelta(minutes=settings.jwt_ttl_minutes)
    return {
        "sub": sub,
        "tenant_id": tenant_id,
        "exp": exp,
    }


def create_token(sub: str, tenant_id: str) -> str:
    """Create a JWT token signed with the configured secret."""
    settings = get_settings()
    claims = _make_claims(sub, tenant_id)
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    return token


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.
    Raises InvalidTokenError if verification fails or the tenant_id does not match
    the current company.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    token_tenant = payload.get("tenant_id")
    if token_tenant != settings.company_id:
        raise InvalidTokenError("Token tenant does not match current company")
    return payload
