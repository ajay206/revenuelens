CREATE TABLE IF NOT EXISTS llm_cache (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    prompt_hash text NOT NULL,
    model text,
    response text NOT NULL,
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, prompt_hash)
);

ALTER TABLE llm_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_cache FORCE ROW LEVEL SECURITY;

CREATE POLICY llm_cache_tenant_isolation ON llm_cache
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON llm_cache TO revenuelens_app;
