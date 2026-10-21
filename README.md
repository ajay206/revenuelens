# RevenueLens

AI‑powered revenue assurance that finds billing leaks – read‑only, no data leaves your system.

## Try it in one command

```bash
curl -O https://raw.githubusercontent.com/ajay206/revenuelens/main/docker-compose.demo.yml
docker compose -f docker-compose.demo.yml up
```

Open your browser to **http://localhost:8000**.

### Demo credentials (synthetic demo‑only)

| Email                     | Password          |
|---------------------------|-------------------|
| demo@revenuelens.local    | revenuelens-demo  |

These credentials are **synthetic** and only work for the demo environment.

> **Note:** All data is synthetic – Nimbus Telecom, ~500 customers, with planted billing leaks. No real customer data is used.

#### Optional LLM key

* Provide `GROQ_API_KEY`, `OPENROUTER_API_KEY`, or `GEMINI_API_KEY` as environment variables to get real AI‑generated leak stories.
* If none are set, a **fake** LLM implementation is used (still shows the UI flow).

#### What to click

1. **Leaks** – list of detected billing leaks.  
2. Click a leak → **Story** with citations.  
3. **Fixes** – draft a fix, approve it in the queue.  
4. **Reports** – download CSV / PDF summaries.  
5. **Docs** – on‑demand documentation (e.g., “document plan NMB_MAX_699”).

The demo runs the image `ghcr.io/ajay206/revenuelens:latest`.

When you are done:

```bash
docker compose -f docker-compose.demo.yml down -v
```

---
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

## Step 2: Nimbus Telecom legacy simulator  

The second step of the RevenueLens interview provides a synthetic “legacy” billing database that mimics the messiness of an old telco platform.  

### What you get  
* A PostgreSQL schema **`nimbus`** with 13 legacy‑shaped tables (no foreign keys).  
* Deterministic seed data (500 customers, usage from July‑September 2026).  
* 8 planted leaks of each of the 8 leak types, plus 2 configuration‑conflict cases.  
* `ground_truth.json` that lists every planted leak, the affected record IDs and the monetary impact.  
* An **oracle** (`legacy_sim/oracle.py`) that can automatically verify that the leaks are present and that clean records have no false positives.

### How to run it  

```bash
# 1. Generate the CSVs and ground‑truth file
python -m legacy_sim generate --out data/legacy_sim

# 2. Load them into a Postgres instance (replace URL with your DB)
python -m legacy_sim load --database-url postgresql://user:pass@localhost:5432/legacy-db data/legacy_sim

# 3. See a quick summary
python -m legacy_sim summary --database-url postgresql://user:pass@localhost:5432/legacy-db
```

Or use the provided Docker compose profile, which spins up a dedicated `legacy-db` container and runs the whole pipeline in one command:

```bash
docker compose --profile legacy-sim run --rm legacy-sim
```

The CI pipeline runs this command automatically as an end‑to‑end test.

### Expected summary output  

```
CUST_MSTR: 500 rows
RT_PLAN_CFG: 6 rows
TRF_RATE_CFG: 18 rows
DISC_CFG: 4 rows
CONTRACT_TERMS: 500 rows
SUBSCR_MSTR: 756 rows
SUBSCR_DISC: 242 rows
RENEW_LOG: 99 rows
USG_CDR: 21957 rows
RTD_EVT: 21949 rows
BILL_HDR: 2244 rows
BILL_DTL: 24684 rows
PYMT_TXN: 2097 rows
unrated_usage: 8 leaks, impact 77.33
rated_not_invoiced: 8 leaks, impact 103.97
tariff_mismatch: 8 leaks, impact 509.2
expired_discount: 8 leaks, impact 379.35
provisioned_not_billed: 8 leaks, impact 4776.0
missed_renewal: 8 leaks, impact 13083.0
unmatched_payment: 8 leaks, impact 12000.0
duplicate_charge: 8 leaks, impact -3992.0
Overall impact: 26936.85
```

Use the oracle to validate your detection logic:

```bash
python -m legacy_sim oracle --database-url postgresql://... data/legacy_sim/ground_truth.json
```

If the oracle returns “All leaks verified”, your solution matches the ground truth and you’re ready for the next step.  
