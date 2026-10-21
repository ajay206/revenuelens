import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://revenuelens:revenuelens@localhost:5432/revenuelens"
    company_id: str = ""
    company_name: str = "Demo Company"
    jwt_secret: str = ""
    jwt_ttl_minutes: int = 60


def get_settings() -> Settings:
    """
    Build a Settings instance from environment variables.
    Raises RuntimeError if required variables are missing.
    """
    company_id = os.getenv("COMPANY_ID")
    if not company_id:
        raise RuntimeError("COMPANY_ID environment variable is required")
    jwt_secret = os.getenv("JWT_SECRET")
    if not jwt_secret:
        raise RuntimeError("JWT_SECRET environment variable is required")
    # Optional overrides
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://revenuelens:revenuelens@localhost:5432/revenuelens",
    )
    company_name = os.getenv("COMPANY_NAME", "Demo Company")
    ttl = os.getenv("JWT_TTL_MINUTES")
    try:
        ttl_int = int(ttl) if ttl is not None else 60
    except ValueError:
        ttl_int = 60

    return Settings(
        database_url=database_url,
        company_id=company_id,
        company_name=company_name,
        jwt_secret=jwt_secret,
        jwt_ttl_minutes=ttl_int,
    )
