-- RevenueLens multi-tenant schema initialization
-- All tables use UUID primary keys and enforce tenant isolation via RLS.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- Tenant table (master)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Customer table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id),
    name         TEXT NOT NULL,
    email        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Account table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id),
    customer_id    UUID NOT NULL REFERENCES customer(id),
    account_number TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    balance        NUMERIC(18,4) NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Product offering table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_offering (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Tariff table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tariff (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(id),
    product_offering_id UUID NOT NULL REFERENCES product_offering(id),
    name              TEXT NOT NULL,
    unit_price        NUMERIC(18,4) NOT NULL,
    usage_type        TEXT NOT NULL, -- e.g. 'usage', 'subscription'
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Discount table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discount (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    code          TEXT NOT NULL,
    percentage    NUMERIC(5,2) NOT NULL,
    amount        NUMERIC(18,4) NOT NULL DEFAULT 0,
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Subscription table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscription (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES tenant(id),
    customer_id        UUID NOT NULL REFERENCES customer(id),
    product_offering_id UUID NOT NULL REFERENCES product_offering(id),
    discount_id        UUID REFERENCES discount(id),
    start_date         DATE NOT NULL,
    end_date           DATE,
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Usage record table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_record (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id),
    account_id     UUID NOT NULL REFERENCES account(id),
    tariff_id      UUID NOT NULL REFERENCES tariff(id),
    quantity       NUMERIC(18,4) NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Rated event table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rated_event (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenant(id),
    usage_record_id  UUID NOT NULL REFERENCES usage_record(id),
    amount           NUMERIC(18,4) NOT NULL,
    tax_amount       NUMERIC(18,4) NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Invoice table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    account_id  UUID NOT NULL REFERENCES account(id),
    invoice_date DATE NOT NULL,
    due_date    DATE NOT NULL,
    total_amount NUMERIC(18,4) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Invoice line table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_line (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id),
    invoice_id     UUID NOT NULL REFERENCES invoice(id),
    rated_event_id UUID REFERENCES rated_event(id),
    description    TEXT NOT NULL,
    amount         NUMERIC(18,4) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Payment table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    invoice_id  UUID NOT NULL REFERENCES invoice(id),
    amount      NUMERIC(18,4) NOT NULL,
    method      TEXT NOT NULL,
    paid_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Contract table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contract (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    customer_id   UUID NOT NULL REFERENCES customer(id),
    account_id    UUID NOT NULL REFERENCES account(id),
    start_date    DATE NOT NULL,
    end_date      DATE,
    terms         JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Indexes on tenant_id for every tenant-scoped table
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_customer_tenant_id          ON customer(tenant_id);
CREATE INDEX IF NOT EXISTS idx_account_tenant_id           ON account(tenant_id);
CREATE INDEX IF NOT EXISTS idx_product_offering_tenant_id  ON product_offering(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tariff_tenant_id            ON tariff(tenant_id);
CREATE INDEX IF NOT EXISTS idx_discount_tenant_id          ON discount(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscription_tenant_id      ON subscription(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_record_tenant_id      ON usage_record(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rated_event_tenant_id       ON rated_event(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoice_tenant_id           ON invoice(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoice_line_tenant_id      ON invoice_line(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_tenant_id           ON payment(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contract_tenant_id          ON contract(tenant_id);

-- -----------------------------------------------------------------------------
-- Row Level Security: ENABLE and FORCE on every table
-- -----------------------------------------------------------------------------
ALTER TABLE tenant          ENABLE ROW LEVEL SECURITY; ALTER TABLE tenant          FORCE ROW LEVEL SECURITY;
ALTER TABLE customer        ENABLE ROW LEVEL SECURITY; ALTER TABLE customer        FORCE ROW LEVEL SECURITY;
ALTER TABLE account         ENABLE ROW LEVEL SECURITY; ALTER TABLE account         FORCE ROW LEVEL SECURITY;
ALTER TABLE product_offering ENABLE ROW LEVEL SECURITY; ALTER TABLE product_offering FORCE ROW LEVEL SECURITY;
ALTER TABLE tariff          ENABLE ROW LEVEL SECURITY; ALTER TABLE tariff          FORCE ROW LEVEL SECURITY;
ALTER TABLE discount        ENABLE ROW LEVEL SECURITY; ALTER TABLE discount        FORCE ROW LEVEL SECURITY;
ALTER TABLE subscription    ENABLE ROW LEVEL SECURITY; ALTER TABLE subscription    FORCE ROW LEVEL SECURITY;
ALTER TABLE usage_record    ENABLE ROW LEVEL SECURITY; ALTER TABLE usage_record    FORCE ROW LEVEL SECURITY;
ALTER TABLE rated_event     ENABLE ROW LEVEL SECURITY; ALTER TABLE rated_event     FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice         ENABLE ROW LEVEL SECURITY; ALTER TABLE invoice         FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice_line    ENABLE ROW LEVEL SECURITY; ALTER TABLE invoice_line    FORCE ROW LEVEL SECURITY;
ALTER TABLE payment         ENABLE ROW LEVEL SECURITY; ALTER TABLE payment         FORCE ROW LEVEL SECURITY;
ALTER TABLE contract        ENABLE ROW LEVEL SECURITY; ALTER TABLE contract        FORCE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- Row Level Security policies
-- -----------------------------------------------------------------------------
-- Tenant table uses its own id as the isolation key
CREATE POLICY tenant_isolation ON tenant
    FOR ALL
    USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation ON customer        FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON account         FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON product_offering FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON tariff          FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON discount        FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON subscription    FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON usage_record    FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON rated_event     FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON invoice         FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON invoice_line    FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON payment         FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY tenant_isolation ON contract        FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- -----------------------------------------------------------------------------
-- Create application role (idempotent) and grant privileges
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_roles WHERE rolname = 'revenuelens_app'
    ) THEN
        CREATE ROLE revenuelens_app NOLOGIN;
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO revenuelens_app;
