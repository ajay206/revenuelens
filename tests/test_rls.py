import uuid

import pytest
from psycopg import errors


def insert_tenant(conn, tenant_id, name):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant (id, name) VALUES (%s, %s);",
            (tenant_id, name),
        )


def insert_customer(conn, tenant_id, name, email):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer (tenant_id, name, email) VALUES (%s, %s, %s);",
            (tenant_id, name, email),
        )


def test_row_level_security(db):
    # Insert tenants and customers as superuser
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    insert_tenant(db, tenant_a, "Tenant A")
    insert_tenant(db, tenant_b, "Tenant B")

    insert_customer(db, tenant_a, "Alice", "alice@example.com")
    insert_customer(db, tenant_b, "Bob", "bob@example.com")

    # Use the application role with tenant A set
    with db.transaction(), db.cursor() as cur:
        cur.execute("SET LOCAL ROLE revenuelens_app;")
        cur.execute(
            "SELECT set_config('app.tenant_id', %s, true);",
            (tenant_a,),
        )
        cur.execute("SELECT id, tenant_id, name FROM customer;")
        rows = cur.fetchall()
        assert len(rows) == 1
        # Compare tenant_id as string to avoid UUID vs str mismatch
        assert str(rows[0][1]) == tenant_a

        # Attempt to insert a customer for tenant B -> should fail
        with pytest.raises(errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO customer (tenant_id, name, email) VALUES (%s, %s, %s);",
                (tenant_b, "Eve", "eve@example.com"),
            )

    # Without tenant context, no rows should be visible
    with db.transaction(), db.cursor() as cur:
        cur.execute("SET LOCAL ROLE revenuelens_app;")
        # tenant_id not set
        cur.execute("SELECT id FROM customer;")
        rows = cur.fetchall()
        assert rows == []
