# QA Pass & LLM Resilience

This short handbook records the final quality‑assurance checklist that must pass before a **RevenueLens** release can be tagged *qa‑pass*.  
It also describes how the application stays resilient when the large language model (LLM) stack is under pressure.

---  

## LLM stack (ordered by priority)

| Priority | Model / Provider | Cost tier | Notes |
|----------|------------------|----------|-------|
| 1 | `groq/llama‑3.1‑8b‑instruct` (low‑cost) | low | First‑line cheap model |
| 2 | `openai/gpt‑oss‑120b` | low | Fallback when Groq is unavailable |
| 3 | `openrouter/poolside‑laguna‑s‑2.1` | free | Community pool; good for bulk generation |
| 4 | `nvidia/nemotron‑3‑ultra‑550b‑a55b` | free | High‑capacity free tier |
| 5 | `gemini/gemini‑3.1‑flash‑lite` | free | Final deterministic fallback |

All calls are wrapped in a **retry‑with‑backoff** helper that:

* Retries **up to 3 ×** per request.  
* Honors `Retry-After` headers on **429** or any **5xx** response.  
* Uses exponential back‑off (≈ 1 s → 2 s → 4 s).  

If every attempt fails, the system switches to a **deterministic fallback story** (hard‑coded narrative). This guarantees that demo‑only setups never crash, even when every external model is offline.

### Cache

* Prompt hash → generated story is stored in the `llm_cache` table (row‑level security limits visibility to the tenant).  
* The cache is **not** used for the fake “demo” model, so each demo run produces a fresh story.

---  

## Currency handling

* The environment variable `RL_CURRENCY` defines the display currency.  
  * Default: `INR` (symbol `₹`).  
* Prompt templates receive the currency symbol; any stray symbols (`$`, `USD`, `Rs.`) are **rewritten** to `₹` before numeric interpolation.  
* All monetary calculations are performed in code, not in the LLM prompt, to avoid rounding drift.

---  

## QA fixes applied in this release

1. **Mobile navigation** – bottom tab bar now visible; the previous hidden sidebar is removed.  
2. **Responsive layout** – no horizontal overflow at **390 px** or **1024 px** breakpoints.  
3. **Friendly HTML error pages** – custom 404/403/409/422 pages (HTML) while API endpoints still return JSON.  
4. **Menu cleanup** – dead **Profile** / **Settings** links removed; menu now only shows the signed‑in user name and role.  
5. **Viewer role restrictions** – viewers no longer see **Draft**, **Approve**, or **Reject** buttons and receive **403** if they attempt to draft a fix via the API.  
6. **Table UI** – searchable & filterable tables, styled pager buttons, and timeline periods formatted as `YYYY‑MM‑DD`.  
7. **Missed‑renewal rows** – answer‑key rows now include a six‑digit `bill_prd` (billing period) field.  
8. **DEMO_SEED handling** – non‑numeric `DEMO_SEED` values emit a warning to `stderr` and a random integer seed (1‑999 999) is used instead.

---  

## How to verify the QA pass

* Run `pytest -q tests/test_qa_pass.py`.  
  * All tests must pass, including the pure‑logic checks (`demo_seed_warning`, `missed_renewal_has_bill_period`).  
* Manually inspect the UI on a mobile device or using Chrome dev tools at the breakpoints above.  
* Confirm that the `llm_cache` table contains rows only for real model calls (the demo model never writes to the cache).  

---  

## Release checklist

- [ ] All tests in `tests/test_qa_pass.py` pass.  
- [ ] Lint (`ruff check .`) reports **no** errors (max line length 120, sorted imports, no unused imports).  
- [ ] Documentation (`docs/handbook/qa-pass.md`) is up‑to‑date and included in the repo.  
- [ ] Environment variables `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `COMPANY_ID`, and `DATABASE_URL` are configured for the test environment.  

When every item is green, the build can be promoted to **qa‑pass**.  

---  

*Prepared by the QA team – keep this file version‑controlled as the single source of truth for future releases.*  
