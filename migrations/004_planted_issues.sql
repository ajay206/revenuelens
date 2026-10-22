-- Demo answer key tables: demo_run and planted_issue
CREATE TABLE IF NOT EXISTS demo_run (
    tenant_id uuid PRIMARY KEY REFERENCES tenant(id),
    seed bigint NOT NULL,
    created_at timestamptz DEFAULT now()
);

ALTER TABLE demo_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE demo_run FORCE ROW LEVEL SECURITY;
CREATE POLICY demo_run_tenant_isolation ON demo_run
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON demo_run TO revenuelens_app;

CREATE TABLE IF NOT EXISTS planted_issue (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    leak_id text NOT NULL,
    check_name text NOT NULL,
    table_name text,
    record_ids jsonb NOT NULL,
    bill_prd text,
    impact_inr numeric(18,2),
    description text,
    cust_no text,
    UNIQUE (tenant_id, leak_id)
);

ALTER TABLE planted_issue ENABLE ROW LEVEL SECURITY;
ALTER TABLE planted_issue FORCE ROW LEVEL SECURITY;
CREATE POLICY planted_issue_tenant_isolation ON planted_issue
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON planted_issue TO revenuelens_app;
GRANT USAGE ON SEQUENCE planted_issue_id_seq TO revenuelens_app;
