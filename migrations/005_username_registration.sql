ALTER TABLE app_user ALTER COLUMN email DROP NOT NULL;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS username text;
CREATE UNIQUE INDEX IF NOT EXISTS app_user_tenant_username_ci ON app_user (tenant_id, lower(username)) WHERE username IS NOT NULL;
ALTER TABLE app_user ADD CONSTRAINT app_user_username_format CHECK (username IS NULL OR username ~ '^[A-Za-z0-9._-]{3,32}$');
ALTER TABLE app_user ADD CONSTRAINT app_user_role_valid CHECK (role IN ('admin','analyst','viewer'));
ALTER TABLE app_user ADD CONSTRAINT app_user_identity CHECK (email IS NOT NULL OR username IS NOT NULL);
