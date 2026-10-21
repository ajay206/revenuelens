# RevenueLens – Step 1

## What is RevenueLens?

RevenueLens is an **AI‑powered revenue‑assurance plug‑in** that connects to a billing system **read‑only** and automatically discovers where revenue is leaking.  
It scans usage, tariffs, discounts, subscriptions, invoices and payments, then surfaces plain‑English stories such as:

* “Customer X has 150 GB unbilled usage since 2024‑09‑15 (≈ ₹ 12 000 loss).”
* “Discount D‑2024‑Q2 was still applied after its expiry date.”

The goal is to give finance and billing teams a single number (“₹ X leaking this month”) and a drill‑down narrative that explains **what**, **since when**, **why**, **how much money** and **who is affected**, together with a suggested corrective action.

> **Step 1** of the project sets up the basic multi‑tenant data platform, a health endpoint, and the CI pipeline. All data used is **synthetic** – no production billing data is included.

---

## Contents of Step 1

| Component | Description |
|-----------|-------------|
| **FastAPI** | Minimal API exposing `/health` (returns `200 OK` with version). |
| **PostgreSQL** | Multi‑tenant schema with a *common model* that mirrors typical billing concepts: |
|  | `tenant`, `customer`, `account`, `product_offering`, `tariff`, `discount`, `subscription`, `usage_record`, `rated_event`, `invoice`, `invoice_line`, `payment`, `contract`. |
|  | Every table has a `tenant_id` column. |
| **Row‑Level Security (RLS)** | A single PostgreSQL role (`app_user`) is used by the application. On each connection the app runs `SET session "app.tenant_id" = <tenant>`; policies restrict all queries to rows matching that tenant. |
| **Docker Compose** | Spins up the API container, the Postgres DB, and a tiny `pytest` runner. |
| **Tests** | Basic unit & integration tests using `pytest`. |
| **CI** | Linting with **ruff**, testing with **pytest**. The CI config runs both on every push. |
| **Synthetic Data** | A small set of generated tenants, customers, usage and invoices used by the tests. No real billing data is required. |

---

## How to Run the Project

```bash
# 1. Clone the repo
git clone <repo‑url>
cd revenue‑lens

# 2. Build and start services
docker compose up --build -d

# 3. Verify the API is alive
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0"}

# 4. Run the test suite
docker compose run --rm test pytest
```

All containers will shut down cleanly with `docker compose down`.

---

## Development & CI

* **Linting** – `ruff check .` (configured in `pyproject.toml`).  
* **Testing** – `pytest` discovers tests under `tests/`.  
* **CI workflow** – defined in `.github/workflows/ci.yml`; it runs `ruff` followed by `pytest`.  

The CI enforces:

1. No lint errors (`ruff`).
2. All tests pass (`pytest`).

---

## Design Rationale (Step 1)

* **Multi‑tenant via RLS** – One shared database simplifies operations, backup, and scaling while guaranteeing data isolation per tenant.  
* **Read‑only plug‑in** – The first version never mutates source tables; it only reads to build its own analytical view.  
* **Synthetic data only** – Enables open‑source distribution without exposing any customer‑specific information.  

Future steps will add AI‑driven rule inference, anomaly detection, and a user‑facing dashboard, but the foundation laid here guarantees a secure, testable, and reproducible environment.

---
