# Step 9: Reports and Docs Generator

This step adds exportable reports (CSV, PDF) and an on-demand documentation generator to RevenueLens.

## Features

### 1. Reports (`/reports`, `/api/reports/*`)

- **CSV Export** (`/api/reports/findings.csv`): All findings with columns:
  - `id`, `check`, `customer_id`, `period`, `impact`, `money`, `table`, `record_ids`, `description`
- **PDF Export** (`/api/reports/findings.pdf`): Formatted report with:
  - Title: `RevenueLens leak report – <company>`
  - Totals line (count, total INR, latest period, month INR)
  - Table of top 200 findings (check, customer, period, INR amount, description truncated to 70 chars)
- Uses `fpdf2` with core Helvetica font (latin-1 only). The helper `_latin1()` replaces `₹` with `INR ` and safely encodes.

### 2. Docs Generator (`/docs`, `/api/docs*`)

**On-demand documentation** built deterministically from the knowledge base (rules, findings, tickets, conflicts) — **no LLM required**.

#### Data Model

- `Fact(text, citations[], confidence)` — confidence is `"confirmed"` or `"needs confirmation"`
- `Section(heading, facts[])`
- `Doc(title, request, level, sections[])`
- `KnowledgeBase(rules, findings, tickets, conflicts)`

#### Classification (`classify()`)

Maps a natural-language request to `(topic, subject)`:

| Priority | Topic | Trigger |
|----------|-------|---------|
| 1 | `plan` | Plan ID match (e.g., `NMB_MAX_699`) |
| 2 | `discount` | Discount ID match (from `discount_pct` rules) |
| 3 | `kt` | "kt" or "knowledge transfer" |
| 4 | `changes` | "change", "history", "what changed" |
| 5 | `discount` | "discount" keyword |
| 6 | `plan` | "plan", "pricing", "tariff" |
| 7 | `invoicing` | "invoic", "billing", "bill" |
| 8 | `leaks` | "leak", "revenue", "audit" |
| 9 | `overview` | fallback |

#### Sections per Topic

| Topic | Sections |
|-------|----------|
| `plan` | Per plan: fee, included data, overage rate, usage rates, observed fee, conflicts, related tickets |
| `discount` | Discount rules (pct + window), discount tickets, expired_discount findings summary |
| `invoicing` | Flow (usage→rating→invoice→payment), findings per check (rated_not_invoiced, duplicate_charge, unmatched_payment, unrated_usage), billing tickets |
| `leaks` | Per check: count, total INR, sample record refs |
| `changes` | Tickets sorted by date |
| `kt` | Intro + Overview + Invoicing + All Plans |
| `overview` | Rule counts by kind, plan count, findings total, conflicts total |

#### Levels (Depth Control)

| Level | Max Facts/Section | Extra |
|-------|-------------------|-------|
| `exec` | 5 | Prepends "Summary" section (total leak INR, rule count, conflict count) |
| `analyst` | 25 | Standard |
| `engineer` | All | Appends "Data Sources" section listing distinct rule sources |

#### Citations & "Needs Confirmation" Rule

- Every fact cites sources: rule sources (`config:table[key=val] (rule RXXXX)`), tickets (`jira:KEY`/`ado:KEY`), findings (`finding:check`), inferred (`inferred:schema mapping`)
- **Hard rule**: Any fact without citations → `confidence = "needs confirmation"` (enforced at end of generation)
- Low-confidence rules (< 0.95) → `needs confirmation`
- Tickets → always `needs confirmation` (show intent, not fact)

#### Output Formats

- **Markdown** (`to_markdown`): Footnote-style citations `[^n]` with Sources section
- **PDF** (`to_pdf`): fpdf2, latin-1 safe via `_latin1()`
- **Confluence Storage Format** (`to_confluence_storage`): XHTML with `<ac:structured-macro ac:name="info">` draft notice, `<em>` for citations, `(needs confirmation)` markers
- **File Draft** (`write_confluence_draft`): Writes `.confluence.xml` to `RL_DRAFTS_DIR` (default `/tmp/revenuelens-drafts`). **Never publishes** — no network calls.

### 3. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/reports` | HTML page with download links |
| GET | `/api/reports/findings.csv` | CSV download (auth required) |
| GET | `/api/reports/findings.pdf` | PDF download (auth required) |
| GET | `/docs` | HTML page with form + rendered doc |
| POST | `/api/docs` | Generate doc → JSON + markdown |
| GET | `/api/docs/export` | Export doc as md/pdf/confluence (query params: request, level, format) |

### 4. Templates

- `reports.html` — extends `base.html`, simple card grid with download buttons
- `docs.html` — extends `base.html`, form with textarea + level select, renders generated doc with "needs confirmation" badges, export links use `urlencode`

### 5. Running Tests

```bash
# Unit tests (no DB)
pytest tests/test_step9_reports_docs.py -v -k "not client"

# Integration tests (require DATABASE_URL, seeded)
export DATABASE_URL=postgresql://user:pass@localhost/db
pytest tests/test_step9_reports_docs.py -v -k "client"
```

### 6. Dependencies

Added `fpdf2` to `pyproject.toml`:

```toml
dependencies = [
    ...
    "fpdf2",
]
```

### 7. Navigation

Updated `base.html` nav (see `app/templates/_nav.txt`):

```html
<nav><a href="/">Leaks</a> · <a href="/fixes">Fixes</a> · <a href="/reports">Reports</a> · <a href="/docs">Docs</a> · <a href="/logout">Logout</a></nav>
