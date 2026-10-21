# RevenueLens – Step 1

## What is RevenueLens?

RevenueLens is an **AI‑powered revenue‑assurance plug‑in** that connects to a billing system **read‑only** and automatically discovers where revenue is leaking.  
It scans usage, tariffs, discounts, subscriptions, invoices and payments, then surfaces plain‑English stories such as:

* “Customer X has 150 GB unbilled usage since 2024‑09‑15 (≈ ₹ 12 000 loss).”
* “Discount D‑2024‑Q2 was still applied after its expiry date.”

The goal is to give finance and billing teams a single number (“₹ X leaking this month”) and a drill‑down narrative that explains **what**, **since when**, **why**, **how much money** and **who is affected**, together with a suggested corrective action.

> **Step 1** of the project sets up the basic isolated‑deployment data platform, a health endpoint, and the CI pipeline. All data used is **synthetic** – no production billing data is included.

---

## New Architecture – One Isolated Stack per Company

Each company gets its own Docker Compose stack:

* A dedicated PostgreSQL container with its own volume.
* A private internal Docker network (no DB host port exposed).
* Secrets stored in `deployments/<company‑slug>/.env` (git‑ignored, `chmod 600`).
* The stack is launched with  
  ```bash
  scripts/new-company.sh <slug> [name]   # generates .env and runs compose
  ```
* The API always runs with the **COMPANY_ID** of its stack, and row‑level security (RLS) is kept as a defense‑in‑depth measure.

---

## How to Run a New Company Instance

```bash
# 1. Create a new company stack (generates .env and starts containers)
scripts/new-company.sh acme AcmeCorp   # <slug> = acme, optional name

# 2. Verify the API is alive (bound to 127.0.0.1 on a unique port)
curl http://127.0.0.1:8100/health
# → {"status":"ok","version":"0.1.0"}
```

The script:

* Generates a random PostgreSQL password, a JWT secret, `COMPANY_ID`, an admin password, and picks a free API port starting from 8100.
* Writes these values to `deployments/<slug>/.env` (git‑ignored, mode 600).
* Runs `docker compose -p rl-<slug> --env-file deployments/<slug>/.env up -d --build`.
* Set `SKIP_UP=1` if you only want to generate the env file without starting containers.

---

## Authentication & Tenant Isolation

* **Login** – `POST /auth/login` checks the `app_user` table (tenant‑scoped, bcrypt password).  
  On success it returns a JWT signed with the **instance’s secret** and containing the claim `tenant_id = <COMPANY_ID>`.
* **JWT validation** – The API validates the signature **and** that the `tenant_id` claim matches the instance’s `COMPANY_ID`. Tokens issued by another stack are rejected.
* **Request handling** – A FastAPI dependency runs `SET session "app.tenant_id" = <COMPANY_ID>` on every DB connection, so PostgreSQL RLS policies continue to enforce row‑level isolation.
* **Seeding** – `python -m app.seed` creates the tenant row and the first admin user from `ADMIN_EMAIL` / `ADMIN_PASSWORD` defined in the env file. The container entrypoint runs migrations, seeds, then starts `uvicorn`.

---

## Running Tests

```bash
# Local development (uses the same env vars as the container)
export DATABASE_URL=postgresql://app_user:...@localhost:5432/rl
export COMPANY_ID=acme
export JWT_SECRET=...

pip install -e '.[dev]'
pytest
```

Test suite includes:

* Health endpoint check.
* Successful login.
* Wrong password → 401.
* Token signed with a foreign secret → 401.
* Token with mismatched `tenant_id` claim → 401.
* No token → 401.
* RLS isolation test confirming rows of other tenants are invisible.
* Verification that the `new-company.sh` script creates a usable stack.

All tests run against the isolated stack’s database, guaranteeing true tenant separation.

---

## Development & CI

* **Linting** – `ruff check .` (configured in `pyproject.toml`).  
* **Testing** – `pytest` discovers tests under `tests/`.  
* **CI workflow** – defined in `.github/workflows/ci.yml`; it runs `ruff` then `pytest`.  

The CI enforces:

1. No lint errors.
2. All tests pass, including the RLS isolation test.

---

## Design Rationale (Step 1)

* **One stack per company** – Eliminates the need to expose a DB port, keeps each company’s data and secrets completely separate at the container level, and simplifies operational concerns (backups, resource limits).  
* **Row‑Level Security** – Still used as a defense‑in‑depth layer; even if a container is compromised, the database will refuse queries that do not match the tenant context.  
* **Synthetic data only** – Enables public distribution and fast CI without any PII.

Future steps will add AI‑driven rule inference, anomaly detection, and a user‑facing dashboard, all built on top of this secure, isolated foundation.  

---  
