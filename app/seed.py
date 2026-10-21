import os

from .config import get_settings
from .db import company_conn
from .security import hash_password


def main() -> None:
    settings = get_settings()
    tenant_id = settings.company_id
    tenant_name = settings.company_name

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must be set")

    with company_conn() as conn:
        # Ensure tenant row exists
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tenant (id, name, created_at)
                VALUES (%s, %s, now())
                ON CONFLICT (id) DO NOTHING
                """,
                (tenant_id, tenant_name),
            )
        # Upsert admin user
        password_hash = hash_password(admin_password)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_user (id, tenant_id, email, password_hash, role, created_at)
                VALUES (gen_random_uuid(), %s, %s, %s, 'admin', now())
                ON CONFLICT (tenant_id, email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role
                """,
                (tenant_id, admin_email, password_hash),
            )
        conn.commit()


if __name__ == "__main__":
    main()
