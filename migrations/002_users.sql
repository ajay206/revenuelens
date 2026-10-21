-- Create the app_user table with RLS and policies
CREATE TABLE app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    email text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'admin',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

-- Index for faster tenant lookups
CREATE INDEX idx_app_user_tenant_id ON app_user (tenant_id);

-- Enable Row Level Security and force it
ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_user FORCE ROW LEVEL SECURITY;

-- Policy to isolate rows per tenant
CREATE POLICY tenant_isolation ON app_user
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- Grant permissions to the application role
GRANT SELECT, INSERT, UPDATE, DELETE ON app_user TO revenuelens_app;
