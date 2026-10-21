# RevenueLens: AI revenue assurance that plugs into any billing system (design v0.4)

Working name, changeable. Synthetic data only. No CSG code, data or SingleView internals.

## 1. The problem
Telcos, MVNOs, ISPs and usage-based SaaS lose 1-3% of revenue to billing leaks: unbilled usage,
wrong tariffs, expired discounts still applied, failed renewals, services provisioned but never billed.
Legacy revenue-assurance tools are expensive, slow to set up, and explain nothing.

## 2. Product rules
1. Plug in, never replace. Day one is read-only.
2. Every finding is explained in plain words: what, since when, why (root cause), money impact, who is affected, what to do.
3. AI acts, not instructs: it drafts the fix; a human approves; later it applies small fixes within limits.
4. Screens simple enough for a child: one number on top ("Rs X leaking this month"), click for the story.

## 3. Who buys
- First: mid-size telcos, MVNOs, ISPs, SaaS with usage billing. Buyer: CFO / head of billing.
- Later: utilities, logistics, any business that bills on usage.

## 4. Architecture
```
Legacy billing (DB replica / CDC / files / APIs)
        |  adapters (read-only)
        v
Ingest + AI field mapping  ->  Common model (TMF SID-style: customer, product, usage, rated event, invoice, payment, contract)
        v
Reconciliation engine (rules + detectors + anomaly models)
        v
Findings store (event-sourced, per tenant)
        v
AI explainer agent (LLM + RAG over contracts/tariffs) -> plain-English story + money impact
        v
Fix drafts -> approval queue -> (later) actions via legacy system's own APIs
        v
Dashboard + reports + API
```
- Multi-tenant from day one (tenant_id on every row, row-level security).
- Every finding links back to source records, so auditors can verify it.
- LLM: cheap hosted model; fake model in CI.

## 4a. How RevenueLens learns a customer's billing (onboarding)
The backend is the source of truth; documents are optional.
1. **Schema discovery.** Read table/column names, types, keys and sample rows from the read replica. AI proposes what each table means (usage, rated events, invoices, payments, catalog). Billing expert approves/corrects in one click.
2. **Catalog from config tables or APIs.** Plans, tariffs, rate tables, discounts and bundles live in the system's own config tables or catalog APIs/exports (often TMF Product Catalog style). AI turns rows into readable rules, each linked to its source row.
3. **Rules inferred from billed data.** Where logic is hidden in app code, infer candidate rules from rated records (e.g. "Plan X pays Rs 10/MB after 2 GB"). An analyst confirms in plain language.
4. **Documents if available.** Tariff sheets, contracts, rate cards: extracted into rules with page references.
4b. **Work history: ADO, Jira, Confluence.** Read-only connectors index tickets (Azure DevOps work items, Jira issues), their comments, linked commits/changes, and Confluence pages. AI extracts: plan launches and price changes with dates, one-off deals and exceptions, known billing defects and their fixes, and the reasoning behind odd config. Each learned rule cites its ticket/page. Uses: explain why a rule exists, date when a leak started (e.g. a config change ticket), separate known/accepted exceptions from real leaks, and spot recurring defect patterns.
   Source priority when they disagree: backend config and billed data (what actually happens) > tickets/wiki (what was intended) > documents; conflicts go to a human as a question, and intended-vs-actual gaps are themselves candidate leaks.
5. **Targeted questions only for gaps.** e.g. "40 customers get 15% off with no discount record. Corporate deal?"
6. **Prove it: bill replay.** Recalculate last month's bills from learned rules and compare to actual bills. Mismatch = wrong rule or real leak; humans review. Go live once ~99% of past bills reproduce.
7. **Drift watch.** New plans, columns or values, or replay mismatches, trigger a confirm-with-human step.
## 4c. Docs on demand
After learning the system, RevenueLens writes documentation when asked, in plain language, always from the current learned model (never stale):
- **Ask in words:** "Document Plan X", "How is roaming rated?", "Write a KT doc for the invoicing flow", "What changed in discounts this quarter?"
- **Doc types:** plan/tariff catalog, rating and charging rules, data dictionary (tables, columns, meaning), end-to-end flow diagrams (usage to invoice to payment), exceptions and special deals register, change history, known defects and fixes, onboarding/KT guides for new staff, audit packs.
- **Every statement cites its source:** table/config row, billed-data evidence, ticket, Confluence page, or document page.
- **Audience levels:** executive summary, analyst detail, engineer detail.
- **Formats:** Markdown/PDF/Word download, or publish back to Confluence as a draft for human approval (never overwrites existing pages).
- **Stays current:** regenerate on request; drift watch flags docs that are out of date.
- Gaps the AI is unsure about are marked "needs confirmation" instead of guessed.

## 4b. Trust and rollout plan
1. **Shadow run beside the RA team (1-3 months).** Same data; compare finds, misses and false positives.
2. **Proof on every finding.** Links to exact usage records, invoice lines, catalog rows / contract clauses.
3. **Deterministic rules for money math; AI for mapping, ranking, explaining and suggesting new checks** (new checks need human approval).
4. **Read-only; fixes are drafts until approved;** full audit log.
5. **Data stays with them:** deploy in their cloud or on-prem.
6. **Pay on results:** share of recovered revenue.
Outcome: the RA team shrinks from line-by-line checking to reviewing AI findings.

## 5. Leak checks (v1)
1. Usage recorded but not rated
2. Rated but not invoiced
3. Tariff on invoice differs from contract
4. Discount/promo past its end date still applied
5. Service active in provisioning but no billing account/charge
6. Failed or missed renewals
7. Payments not matched to invoices
8. Duplicate charges (customer overbilled: churn and regulatory risk)

## 6. The demo
1. Synthetic billing system (reuse BillPilot data, ~500 customers, planted leaks + ground_truth.json).
2. Connect RevenueLens read-only to an unfamiliar synthetic billing DB (no docs); watch it map tables, learn plans/tariffs from config and billed data, and replay last month's bills.
3. Scan runs; dashboard shows Rs lost this month and top leaks.
4. Click a leak: plain story, source records, root cause.
5. Approve fix; "recovered" counter goes up.
6. Ask "Write a KT doc for how Plan X is billed"; get a cited doc in seconds.
7. Eval score: precision/recall against ground truth.

## 7. Pricing
- Free 3-month scan (the hook).
- 10-20% of recovered revenue, or Rs 1-5 lakh/month subscription by size.
- Enterprise: annual, on-prem option.

## 8. Build steps (one PR each, each needs Ajay's approval)
1. Repo, CI, multi-tenant schema for the common model
2. Synthetic legacy billing source with planted leaks + ground truth
3. Read-only adapter (DB replica) + schema discovery + AI field mapping + catalog/rule learning + bill replay
4. Reconciliation engine with the 8 leak checks + eval harness
5. AI explainer agent (plain-English stories, money impact)
6. Dashboard (one-number home, leak story page)
7. Fix drafts + approval queue + audit trail
8. Second adapter (CSV/file exports) + knowledge connectors (Jira, ADO, Confluence; synthetic tickets/pages in demo)
9. Reports (PDF/CSV), docs-on-demand generator (with source citations, Confluence draft publish) and API
10. Deploy (free tier), demo video, LinkedIn post draft

## 9. Metrics
Leak detection precision/recall, bill-replay match rate, onboarding time, money found, time to first finding, false-positive rate, explanation clarity (human rating).

## 10. Why it can compete
Incumbent RA vendors are slow, costly and opaque. RevenueLens is fast to connect, explains every finding,
charges on results, and the same engine works beyond telecom.
