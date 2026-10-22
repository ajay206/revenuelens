# User Registration Handbook

## Overview
RevenueLens supports optional self‑registration for new users. When enabled, anyone can create an account through the web UI. New accounts receive the **viewer** role, which grants read‑only access to most resources while prohibiting fix approvals. Administrators can later promote users to **analyst** or **admin** via direct database updates.

## Feature Toggle
- Controlled by the environment variable `ALLOW_REGISTRATION`.
- Default: **false** (registration disabled).
- Enabled in the demo stack (`docker‑compose.demo.yml`) and can be turned on for a production tenant by adding `ALLOW_REGISTRATION=true` to the tenant’s `.env` file.

## Registration Flow

1. **Landing Page** – The login page (`/login`) displays a **Create account** link.
2. **Form** – Clicking the link routes to `/register` where the user enters:
   - **Username** – 3‑32 characters, letters, digits, `.`, `_`, `-`. Unique per tenant, case‑insensitive.
   - **Password** – Minimum 8 characters.
   - **Confirm password** – Must match the password field.
3. **Validation** – Front‑end validation mirrors back‑end rules. Errors are shown as friendly messages:
   - `409 Conflict` – “That username is already taken”.
   - `422 Unprocessable Entity` – “Password is too weak”, “Invalid username format”, etc.
   - `403 Forbidden` – “Self-registration is turned off for this instance. Ask your admin for an account.”.
   - `429 Too Many Requests` – “Too many sign‑ups, try again later”.
4. **Rate Limiting** – In‑memory limiter permits **10** registrations per IP address per 10‑minute window.
5. **Account Creation** – On success the server creates a user row:
   - `username` stored lower‑cased for case‑insensitivity.
   - `password_hash` generated with bcrypt.
   - `role` set to `viewer`.
   - `tenant_id` scoped by PostgreSQL Row‑Level Security.
6. **Audit Log** – An entry is written to `audit_log` with:
   - `action = 'user_registered'`
   - `target = 'user:<username>'`
7. **Automatic Login** – The UI logs the user in and redirects to the dashboard.

## API Endpoints

| Method | Path | Request Body | Success Response | Error Responses |
|--------|------|--------------|------------------|-----------------|
| POST | `/auth/register` | `{"username":"...","password":"...","confirm_password":"..."}` | `201 Created` – `{"id":<int>,"username":"...","role":"viewer"}` | `403`, `409`, `422`, `429` with `{"detail":"..."}` |
| POST | `/auth/login` | `{"email":"<username-or-email>","password":"..."}` | Standard login token payload | Standard login errors |

> Note: The login field is still named `email` for backward compatibility but now accepts either a username or an email address.

## Role Permissions

| Role | Can View | Can Approve/Reject Fixes |
|------|----------|--------------------------|
| **viewer** | Findings, Stories, Reports, Docs, Audit, Planted Issues | ❌ (403) |
| **analyst** | Same as viewer | ✅ (via DB grant) |
| **admin** | All resources | ✅ (full control) |

Only **analyst** and **admin** can call:
- `POST /api/fixes/{id}/decision`
- `POST /fixes/{id}/approve`
- `POST /fixes/{id}/reject`

These endpoints return `403 Forbidden` for viewers.

## Database Migration

The migration `migrations/005_username_registration.sql` performs:

```sql
-- Add username column, make email nullable
ALTER TABLE users ADD COLUMN username VARCHAR(32) NOT NULL;
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

-- Unique, case‑insensitive index scoped by tenant
CREATE UNIQUE INDEX uq_user_username_tenant
ON users (tenant_id, lower(username));

-- Role constraint
ALTER TABLE users ADD CONSTRAINT chk_role
CHECK (role IN ('admin','analyst','viewer'));

-- Identity check trigger (email OR username required)
-- (implementation details omitted)
```

All existing tables continue to enforce tenant‑level RLS, ensuring cross‑tenant isolation.

## Testing Overview

The test suite `tests/test_registration.py` validates:

- Successful registration returns `201` and a `viewer` role.
- Duplicate usernames (case‑insensitive) yield `409`.
- Weak passwords trigger `422` with HTML error page.
- Login works with username (via `email` field).
- Viewer cannot approve a fix (`403`).
- Registration disabled returns `403`.
- Audit log entry is created with correct `action` and `target`.
- Registrations are isolated per tenant; a user in tenant A cannot affect tenant B.

The demo smoke test registers a user, checks duplicate handling, and confirms login by username.

## Operational Guidance

1. **Enable Registration** – Add `ALLOW_REGISTRATION=true` to the tenant’s `.env` and restart the service.
2. **Monitor Rate Limits** – Watch the `registration_attempts` metric; adjust the in‑memory limit if needed.
3. **Promote Users** – Use a DB client to update `role` for a user:
   ```sql
   UPDATE users SET role='analyst' WHERE tenant_id = <tid> AND lower(username)='jdoe';
   ```
4. **Audit Compliance** – Verify entries in `audit_log` for `user_registered` to satisfy audit requirements.

--- 

*End of Registration Handbook.*  
