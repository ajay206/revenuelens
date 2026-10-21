# Step 6: Dashboard & Web UI

This step adds a server-rendered dashboard to **RevenueLens** so users can view
revenue leak findings and their structured stories through a web browser.

## What You See

When logged in, the home page (`/`) shows:

- **₹X leaking this month** – the total impact of all findings whose period
  matches the most recent month in the data.
- **₹Y found so far** – the cumulative impact across every finding.
- A count of total leaks detected.
- A **filter dropdown** to narrow the list by leak type (e.g.
  `duplicate_charge`).
- A **table of up to 20 top leaks**, ranked by money impact, each linking to
  `/leaks/{id}` for a full story view.

Clicking a leak opens its **story page**, which displays:

- Title and monetary impact.
- Sections for What, Since When, Root Cause, Who Affected, and What To Do.
- A confidence badge (`high` or `needs confirmation`).
- A **Sources** list containing every citation record and ticket reference.

## Logging In

Navigate to `/login`. Enter your email and password. RevenueLens reads
credentials from the legacy database (`app_user` table). A successful login
sets an **HTTP-only cookie** named `rl_token`.

- On failure, the login form re-renders with "Wrong email or password".
- `/logout` clears the cookie and redirects to `/login`.

## API Endpoints

All `/api/*` endpoints require authentication via either:

1. The `rl_token` cookie, or
2. An `Authorization: Bearer <token>` header.

| Endpoint               | Description                              |
|------------------------|------------------------------------------|
| `GET /api/findings`    | List of all findings (with `?type=` filter). |
| `GET /api/stories`     | List of all stories (`?type=` supported). |
| `GET /api/stories/{id}`| Single story by ID.                      |
| `GET /api/summary`     | Totals, latest period, and per-type breakdown. |

Unauthenticated requests to HTML routes redirect to `/login`; unauthenticated
API calls return `401`.

## Data Sources

Findings come from checking the **legacy database** pointed to by
`LEGACY_DATABASE_URL` (falls back to `DATABASE_URL`) using schema
`LEGACY_SCHEMA` (default: `nimbus`). The discovery and check pipeline uses
`discover()` and `run_checks()` from the findings module.

Stories are generated using `app.explain.explain_all()` with simulated tickets
from `legacy_sim.generator` (seed=42, 500 customers) and the LLM configured via
`app.llm.free_llm_from_env()`.

Results are cached per process. Restart the server or call
`dashboard.reset_cache()` to refresh.

## Running the Tests

```bash
pytest tests/test_step6_dashboard.py
```

Tests use two categories:

- **Unit tests** for `compute_totals()` and `inr()` using hand-built `Finding`
  objects (no database required).
- **Integration tests** that load the legacy simulation if `DATABASE_URL` is
  available. These verify login flow, redirects, filtering, summary totals,
  and 404 behavior.
</arg_value>
