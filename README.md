# RevenueLens

AI‑powered revenue assurance that finds billing leaks – read‑only, no data leaves your system.

## Try it in one command

```bash
curl -O https://raw.githubusercontent.com/ajay206/revenuelens/main/docker-compose.demo.yml
docker compose -f docker-compose.demo.yml up
```

Open your browser to **http://localhost:8765** (change it with `DEMO_PORT=9123`).

### Demo credentials (synthetic demo‑only)

| Email                     | Password          |
|---------------------------|-------------------|
| demo@revenuelens.local    | revenuelens-demo  |

These credentials are **synthetic** and only work for the demo environment.

### Create your own account

Welcome to RevenueLens! To start exploring the platform you first need an account.  
1. Open the login page – you’ll see a **Create account** link right below the sign‑in form.  
2. Click the link; you’ll be taken to **/register** where you must supply a **username**, a **password**, and **confirm password**.  
3. Usernames can be 3‑32 characters and may contain letters, digits, dots, underscores, or hyphens. They are unique per company instance and are case‑insensitive.  
4. Passwords must be at least 8 characters; they are stored securely using bcrypt.  
5. If the registration feature is disabled (the environment variable `ALLOW_REGISTRATION` is `false`), the page will show a friendly *“Self-registration is turned off for this instance. Ask your admin for an account.”* message.  
6. The login field now accepts either your **username** or **email**, so you can sign in with whichever you prefer.  
7. Upon successful registration you will receive the **viewer** role. Viewers can browse findings, stories, reports, documentation, audit logs, and planted issues, but cannot approve or reject fixes.  
8. Admins and analysts retain their existing privileges; analysts can also approve fixes, but they must be granted manually in the database for now.  
9. All registration attempts are rate‑limited – a maximum of 10 sign‑ups per IP address within a 10‑minute window. Exceeding this limit returns a clear *“Too many sign-ups from this address. Try again later.”* error.  
10. Any registration error is presented as a friendly message (e.g., *“That username is already taken”* or *“Password must be at least 8 characters.”*) rather than raw JSON.

In the one-command demo registration is on (`ALLOW_REGISTRATION=true`); per-company stacks default to off.

### Every run plants different issues

- Each fresh start of the demo (i.e. when the database volume is newly created) generates a **random seed** and plants a random mix of leaks:
  - Between **4‑8** of the eight check types are selected.
  - For each selected type, **1‑8** instances are created on randomly chosen customers.
- The seed used for that run is printed in the container logs, e.g. `Demo seed: 123456`.
- You can reproduce a specific run by overriding the seed:

  ```bash
  DEMO_SEED=123456 docker compose -f docker-compose.demo.yml up
  ```

- Restarting the same stack (without tearing down the volume) keeps the same data and therefore the same planted issues.
- To start with a completely fresh demo (new random mix) run:

  ```bash
  docker compose -f docker-compose.demo.yml down -v   # removes the volume
  docker compose -f docker-compose.demo.yml up
  ```

- **Planted issues page** – a new UI page at **/planted** lists every planted issue, its status (Matched / Missed) and links back to the corresponding leak.
- **Answer‑key API** – `GET /api/answer-key` returns the seed, all planted issues with their match status, false‑positives, per‑check counts, precision and recall.  
  The detection logic never reads this answer key; it is stored only for grading.

### What's pre‑loaded

- **Draft fixes** – 8 draft fixes are created on the first run (2 approved, 1 rejected, the rest pending).
- **Audit entries** – the audit log contains entries such as `demo_seeded`, `draft_created`, `fix_approved`, `fix_rejected`, and `report_generated`.
- **Reports page** – “Recently generated reports” shows the CSV/PDF reports generated during the demo. Downloading a report now logs a `report_generated` audit entry.
- **New logo** – a lens with an upward line appears in the sidebar, on the login page, and as the favicon (`/favicon.svg`).

### Pulling the image

- The demo image is hosted at **ghcr.io/ajay206/revenuelens**.  
  The package **must be set to Public** in GitHub Package settings for anonymous pulls.  
  If it is private, authenticate first:

  ```bash
  docker login ghcr.io
  ```

- The image is multi‑arch (`linux/amd64` + `linux/arm64`), so Apple Silicon Macs can run it natively once the new image is published.

### Use a different port

The demo now runs on port **8765** by default.

```bash
docker compose -f docker-compose.demo.yml up
# then open http://localhost:8765
```

To override the port:

```bash
DEMO_PORT=9123 docker compose -f docker-compose.demo.yml up
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `port already allocated` / `address already in use` | Port 8765 is occupied | Run with a different port: `DEMO_PORT=9123 docker compose -f docker-compose.demo.yml up` |
| `no matching manifest for linux/arm64` | Using an older image that lacks arm64 support | Pull the amd64 image explicitly: `DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose -f docker-compose.demo.yml up` |
| `image ... does not provide the specified platform (linux/amd64)` | Docker is trying to run an image without the requested platform | Pull the required base image first: `docker pull --platform linux/amd64 postgres:16` then retry |
| Need to reset the demo state | Stale data or you want a new random seed | `docker compose -f docker-compose.demo.yml down -v` then `docker compose -f docker-compose.demo.yml up` |
| `denied` / `unauthorized` pulling the image | The GitHub package is private or you are not logged in | Make the package public in GitHub or run `docker login ghcr.io` before pulling |


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

## Screenshots

All data is synthetic (Nimbus Telecom demo).

| Page | Light | Dark |
|---|---|---|
| Login | ![Login light](docs/screenshots/login-light.png) | ![Login dark](docs/screenshots/login-dark.png) |
| Home dashboard | ![Home dashboard light](docs/screenshots/home-light.png) | ![Home dashboard dark](docs/screenshots/home-dark.png) |
| Leak story | ![Leak story light](docs/screenshots/story-approved-light.png) | ![Leak story dark](docs/screenshots/story-approved-dark.png) |
| Fix approval queue | ![Fix approval queue light](docs/screenshots/fixes-light.png) | ![Fix approval queue dark](docs/screenshots/fixes-dark.png) |
| Reports | ![Reports light](docs/screenshots/reports-light.png) | ![Reports dark](docs/screenshots/reports-dark.png) |
| Docs on demand | ![Docs on demand light](docs/screenshots/docs-light.png) | ![Docs on demand dark](docs/screenshots/docs-dark.png) |
| Audit log | ![Audit log light](docs/screenshots/audit-light.png) | ![Audit log dark](docs/screenshots/audit-dark.png) |

Tablet view: ![Home on tablet](docs/screenshots/home-tablet.png)

See the [UI handbook](docs/handbook/ui.md) for design tokens, components and how to retake screenshots.
