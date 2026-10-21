# Step 1 – Interview Explainer

## 1. The problem we’re solving
Telcos, MVNOs, ISPs and usage‑based SaaS providers lose **1‑3 %** of revenue each month because of billing leaks:
* unbilled usage,
* wrong tariffs or expired discounts still applied,
* failed renewals or provisioning without invoicing.

These leaks are hard to detect, expensive to investigate, and traditional revenue‑assurance tools are heavyweight and opaque. RevenueLens aims to be a **read‑only plug‑in** that surfaces the leak in plain English and quantifies the impact.

---

## 2. Design choices made in Step 1

| Choice | Why we chose it |
|--------|-----------------|
| **Row‑Level Security (RLS) vs. separate databases** | One shared PostgreSQL cluster is cheaper to operate, easier to back‑up, and still provides strict isolation because every row carries `tenant_id` and policies enforce it. Separate DBs would multiply operational overhead. |
| **`FORCE ROW LEVEL SECURITY` + non‑superuser role** | The app connects with a regular role (`app_user`). By enabling `FORCE RLS`, even super‑users are forced to obey the policies, preventing accidental cross‑tenant reads. |
| **Plain SQL migrations (Alembic)** | Keeps the schema version‑controlled, database‑agnostic, and easy for newcomers to read. No ORM‑specific magic – the model mirrors the TMF SID style directly. |
| **Synthetic data only** | Guarantees the repository can be public and CI can run without any PII. It also makes the isolation test deterministic. |

### How the isolation test proves RLS works
1. The test creates two tenants (`t1`, `t2`) and inserts identical rows for each (customer, invoice, etc.). |
2. It opens a DB connection, sets `app.tenant_id = 't1'`, and queries the `invoice` table. |
3. The assertion checks that **only** rows belonging to `t1` are returned. |
4. The same is repeated for `t2`.  

If any row from the other tenant appears, the test fails, proving the RLS policy is active and correctly scoped.

---

## 3. Likely interview questions & short answers

| Question | Short answer |
|----------|--------------|
| **Why not just use a separate schema per tenant?** | Schemas still share the same physical tables, so a bug could query the wrong schema. RLS enforces row‑level checks at the engine level, independent of application code. |
| **What does `FORCE ROW LEVEL SECURITY` protect?** | It makes sure *all* users, even superusers, are subject to the RLS policies, eliminating accidental privilege‑escalation leaks. |
| **How do you set the tenant context in the app?** | On each request the FastAPI dependency runs `SET session "app.tenant_id" = <tenant-id>`; subsequent queries automatically filter via the RLS policy. |
| **Why use synthetic data for tests?** | To keep the repo public‑friendly, avoid any real‑customer data, and make the isolation test deterministic and fast. |
| **What would you change for production?** | Add read‑replica scaling, enforce TLS, rotate credentials, and move the synthetic data loader to a migration step that only runs in dev. |
| **How does the CI ensure code quality?** | `ruff` enforces style & linting, while `pytest` runs unit and integration tests (including the RLS isolation test). The GitHub Actions workflow aborts on any failure. |
| **What’s the next step after Step 1?** | Introduce the AI ingestion pipeline, rule inference, and the findings store, all still respecting the same tenant‑scoped model. |

---

## 4. TL;DR for a hiring manager
*Step 1* builds a **secure, multi‑tenant PostgreSQL foundation** with **row‑level security**, a tiny **FastAPI health endpoint**, and a **CI pipeline** that guarantees isolation. The design choices (RLS, forced policies, synthetic data) show an emphasis on security, testability, and low operational cost—exactly what a revenue‑assurance plug‑in needs before we start plugging AI on top of real billing data.  
