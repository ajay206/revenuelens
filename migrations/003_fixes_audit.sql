-- Step 7: Fix drafts, approval queue, and audit trail

-- fix_draft table
CREATE TABLE IF NOT EXISTS fix_draft (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    leak_key text NOT NULL CHECK (leak_key ~ '^[^:]+:.+$'),
    check_name text,
    customer_id text,
    amount numeric(18,2),
    title text,
    proposed_action text,
    payload jsonb,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','rejected')),
    created_by text,
    decided_by text,
    decided_at timestamptz,
    decision_note text,
    created_at timestamptz DEFAULT now(),
    UNIQUE (tenant_id, leak_key)
);

ALTER TABLE fix_draft ENABLE ROW LEVEL SECURITY;
ALTER TABLE fix_draft FORCE ROW LEVEL SECURITY;

CREATE POLICY fix_draft_tenant_isolation ON fix_draft
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON fix_draft TO revenuelens_app;

-- audit_log table (append-only for the app)
CREATE TABLE IF NOT EXISTS audit_log (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    actor text NOT NULL,
    action text NOT NULL,
    target text,
    details jsonb,
    created_at timestamptz DEFAULT now()
);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

CREATE POLICY audit_log_tenant_isolation ON audit_log
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, INSERT ON audit_log TO revenuelens_app;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO revenuelens_app;

-- Make audit_log append-only for revenuelens_app
REVOKE UPDATE, DELETE ON audit_log FROM revenuelens_app;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_fix_draft_status ON fix_draft (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (tenant_id, created_at DESC);
