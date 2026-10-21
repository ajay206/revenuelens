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
| **One isolated Docker‑Compose stack per company** | Gives each customer its own Postgres container, volume, network and secret file. No DB host port is exposed, and the API runs on a unique localhost port. This removes any risk of cross‑company data leakage at the infrastructure level while keeping operations simple (single compose file). |
| **Row‑Level Security (RLS) in addition to isolation** | Even with separate containers, a compromised app could still query the DB without the correct tenant context. RLS forces every SQL statement to respect `app.tenant_id`, providing a second line of defense. |
| **JWT signed with per‑instance secret** | Each stack generates its own `JWT_SECRET`. The token also carries a `tenant_id` claim that must match the stack’s `COMPANY_ID`. Tokens from another stack fail both signature verification and tenant claim check. |
| **`FORCE ROW LEVEL SECURITY` + non‑superuser role** | Guarantees that even a super‑user role cannot bypass the policies, eliminating accidental cross‑tenant reads. |
| **Synthetic data only** | Keeps the repository public‑friendly, avoids any PII, and makes the isolation test deterministic and fast. |

### How the isolation test proves everything works
1. Two company stacks (`acme`, `beta`) are started, each with its own DB.  
2. The test inserts identical rows for both tenants.  
3. It connects to the `acme` DB, sets `app.tenant_id = 'acme'`, and queries a table.  
4. The assertion verifies that **only** `acme` rows are returned.  
5. The same steps are repeated for `beta`.  

If any row from the other tenant appears, the test fails, confirming that both Docker isolation and PostgreSQL RLS are effective.

---

## 3. Likely interview questions & short answers

| Question | Short answer |
|----------|--------------|
| **Why not just run one shared DB with RLS?** | Sharing a DB simplifies backups but exposes a surface where a mis‑configured container could reach another tenant’s data. Full container isolation removes that risk entirely, while RLS remains as a safety net. |
| **Why still keep RLS if containers are isolated?** | Defense in depth: if the application code or environment is compromised, the database will still reject queries that don’t set the correct `app.tenant_id`. |
| **How does JWT isolation work?** | Each stack generates a unique secret. On login the API signs a JWT with that secret and includes `tenant_id`. On every request the API verifies the signature *and* that the claim equals its own `COMPANY_ID`. A token from another stack fails both checks. |
| **What does `FORCE ROW LEVEL SECURITY` protect?** | It forces **all** roles, even superusers, to obey the RLS policies, preventing accidental privilege escalation. |
| **How is the tenant context set in the app?** | A FastAPI dependency runs `SET session "app.tenant_id" = <COMPANY_ID>` for each request, so PostgreSQL policies automatically filter rows. |
| **Why use synthetic data for tests?** | To keep the repo public‑friendly, avoid any real customer data, and make the isolation test deterministic and fast. |
| **What would change for production?** | Use TLS for DB connections, rotate secrets, add monitoring, and possibly move to managed Postgres instances while keeping the per‑company stack concept. |
| **How does the CI ensure isolation?** | Tests spin up a fresh stack for each company, run the RLS isolation test, and verify that tokens from other stacks are rejected. Any failure aborts the workflow. |

---

## 4. TL;DR for a hiring manager
*Step 1* builds a **secure, per‑company Docker Compose deployment** with its own PostgreSQL instance, **row‑level security**, and **JWT isolation**. The design shows a strong focus on security (defense‑in‑depth), testability (automatic isolation tests), and low operational overhead (single compose file, synthetic data). This foundation is ready for the next steps where AI‑driven revenue‑leak detection will be layered on top.  

---  
