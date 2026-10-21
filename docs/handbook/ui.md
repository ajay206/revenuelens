# UI Handbook — RevenueLens

## Goals
- Clean, fast, server-rendered SaaS feel (Stripe/Linear-like) with a dark theme.
- No JS framework, no build step, no CDN JS — only tiny inline scripts for theme and table enhancement.
- Strict readability: no text below 14px, secondary text never lighter than `--text-2`, generous spacing.
- Accessible by default: focus outlines, skip link, ARIA labels, AA contrast, semantic HTML.

---

## Design Tokens

| Token | Light | Dark |
|-------|-------|------|
| `--bg` | `#f8fafc` | `#0b1020` |
| `--surface` | `#fff` | `#111827` |
| `--border` | `#e5e7eb` | `#1f2937` |
| `--text` | `#0f172a` | `#f8fafc` |
| `--text-2` | `#334155` | `#cbd5e1` |
| `--accent` | `#4f46e5` | `#818cf8` |
| `--accent-soft` | `#eef2ff` | *same hue at 15% opacity* |
| `--danger` | `#dc2626` | `#f87171` |
| `--danger-soft` | `#fef2f2` | *15% opacity* |
| `--warn` | `#d97706` | `#fbbf24` |
| `--warn-soft` | `#fffbeb` | *15% opacity* |
| `--ok` | `#16a34a` | `#4ade80` |
| `--ok-soft` | `#f0fdf4` | *15% opacity* |
| `--info` | `#2563eb` | `#60a5fa` |
| `--info-soft` | `#eff6ff` | *15% opacity* |

---

## Typography & Readability
- Font: Inter (Google Fonts) + system fallback stack.
- Base: 16px / 1.5 line-height.
- KPI numbers: 38px, weight 700, color `--text`.
- Table text: minimum 15px, row min-height 48px, cell padding 14px 16px.
- Chart axis labels/values: 14px.
- Headings: 24–28px.
- **Never** use text smaller than 14px.
- Secondary text uses `--text-2` (never lighter).

---

## Layout
### App Shell (CSS Grid)
- Left sidebar: 248px (collapses to 72px icon rail <1024px).
  - Logo "RevenueLens".
  - Nav items: Home (`/`), Fixes (`/fixes`), Reports (`/reports`), Docs (`/docs`), Audit (`/audit`).
  - Active item: `background: var(--accent-soft); color: var(--accent);` + `aria-current="page"`.
- Top bar: 64px.
  - Left: company name.
  - Right: dark-mode toggle (icon button, `aria-label`), user menu button (shows email, dropdown with "Log out" → `/logout`), and a visible "Log out" link.
- Page header (`.page-header`):
  - Breadcrumbs (`.breadcrumbs`, `aria-label="Breadcrumb"`).
  - `h1` title.
  - Optional subtitle and actions.
- Main content area: 24px gap, cards use 24px padding.

### Responsive Breakpoints
- **≥1024px**: full sidebar, grid columns as designed.
- **<1024px**: sidebar → 72px icon rail (labels hidden), grids become 2 columns.
- **<768px**: single column, tables scroll horizontally (`.table-wrap` has `overflow-x: auto`).

---

## Components (Class Names)
| Component | Classes | Notes |
|-----------|---------|-------|
| Card | `.card` | surface bg, 1px border, radius 12px, subtle shadow, 24px padding |
| Card title | `.card-title` | 18px bold |
| KPI grid | `.kpi-grid` | grid gap 24px |
| KPI item | `.kpi` | contains `.kpi-label` (14px, `--text-2`), `.kpi-value` (38px bold, `--text`), optional `.kpi-sub` |
| 2-col grid | `.grid-2` | `grid-template-columns: repeat(2, 1fr)` |
| Buttons | `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-sm` | `<button>` only |
| Badges | `.badge`, `.badge-high` (danger), `.badge-medium` (warn), `.badge-low` (info), `.badge-draft` (warn), `.badge-approved` (ok), `.badge-rejected` (danger) | include text, not color-only |
| Chip | `.chip` | rounded pill for citations, small icon inside |
| Tabs | `.tabs`, `.tab`, `.tab.active` | |
| Page header | `.page-header` | |
| Breadcrumbs | `.breadcrumbs` | |
| Muted text | `.text-muted` | uses `--text-2` |
| Empty state | `.empty-state` | centered icon + title + text |
| Skeleton | `.skeleton` | shimmer loading bar |
| Table wrapper | `.table-wrap` | adds horizontal scroll on mobile |
| Data table | `table.data-table` | sticky header, sortable `th` with `aria-sort` |
| Table toolbar | `.table-toolbar` | search input + filter select (injected by enhancer) |
| Pagination | `.pagination` | Prev/Next + "Showing a–b of n" |
| Form group | `.form-group` | label + input/select/textarea |
| Inputs | native styling via CSS | consistent height, border, radius |
| Timeline | `.timeline` | vertical list with dots |
| Money | `.money` | `font-variant-numeric: tabular-nums`, bold, `--text` |
| Alert error | `.alert-error` | danger-soft bg, danger text, border |

---

## Tables — Data Enhancer
Add `data-enhance` to `table.data-table` to enable the inline enhancer (≈120 lines in `base.html`).

### Attributes
| Attribute | Purpose |
|-----------|---------|
| `data-enhance` | activates enhancer on this table |
| `data-sort="num\|text"` | on `<th>`: makes header clickable; numeric sort uses `td[data-value]` if present |
| `data-value` | on `<td>`: numeric value for sorting (e.g., `1234567.89`) |
| `data-filter-col="N"` | on `<table>`: adds a filter select for column index N (0-based); options from unique cell texts |
| `data-page-size="10"` | on `<table>`: rows per page (default 10) |

### Behaviour
1. On load, `.table-wrap` has `.is-loading` → rows hidden, skeleton rows shown.
2. Enhancer removes `.is-loading`, builds:
   - Toolbar (`.table-toolbar`) with search input (`aria-label="Search table"`) and optional filter select.
   - Pagination (`.pagination`) with Prev/Next and "Showing a–b of n".
   - Sorts rows on header click (toggle asc/desc).
   - Filters rows by search text (case-insensitive, all columns) and selected filter value.
   - Shows empty-state row "No matching results" when filtering leaves zero rows.

### Empty / Loading States
- Loading: `.table-wrap.is-loading` + skeleton rows (`<tr class="skeleton-row"><td colspan="N"><div class="skeleton"></div></td></tr>`).
- Empty: enhancer injects `<tr class="empty-row"><td colspan="N" class="empty-state">No matching results</td></tr>`.

---

## Charts
- Inline SVG only, no dependencies.
- Use `--accent`, `--ok`, `--danger`, `--warn`, `--info` for series.
- Axis labels/values: 14px, `--text-2`.
- Currency labels: compact ₹ format (e.g., `₹12.3L`, `₹4.5Cr`) using `inr_in` in template.
- Keep charts small (card height ~300px), no legends — use direct labels.

---

## Dark Mode
- Inline script in `<head>` (before paint):
  ```html
  <script>
    (function(){
      var theme = localStorage.getItem('rl-theme');
      if (!theme) theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  ```
- Toggle button (in top bar) switches `document.documentElement.dataset.theme` and saves to `localStorage`.
- All colors via CSS variables — no hardcoded hex in component CSS.

---

## Accessibility Checklist
- [ ] Skip-to-content link (`<a href="#main" class="skip-link">Skip to main content</a>`).
- [ ] `:focus-visible` → 3px solid `var(--accent)` with 2px offset.
- [ ] All icon buttons have `aria-label`.
- [ ] Buttons are `<button>`, links are `<a>`.
- [ ] Badges/chips include text (not color-only).
- [ ] Tables: `th` have `aria-sort`, `scope="col"`.
- [ ] Contrast AA for all text (tested in both themes).
- [ ] Responsive: content reflows, no horizontal overflow except tables.
- [ ] ARIA landmarks: `header`, `nav`, `main`, `aside`.

---

## Money Formatting
Two global Jinja filters (defined in `app/dashboard.py`):
- `inr(x)` → Western grouping: `₹1,234,567.89` (kept for API/tests).
- `inr_in(x)` → Indian grouping: `₹12,34,567.89` (**use for all display**).

Example in template:
```jinja
<span class="money" title="{{ inr(totals.found_total) }}">{{ inr_in(totals.found_total) }}</span>
```
- The `title` attribute shows Western format on hover (useful for copy/paste).

---

## Adding a New Page
1. Create template (e.g., `templates/newpage.html`) extending `base.html`.
2. Use the skeleton below.
3. Add route in `app/main.py` (or relevant blueprint).
4. Add nav item in sidebar (if needed) in `base.html`.

### Template Skeleton
```jinja
{% extends "base.html" %}

{% block title %}Page Title — RevenueLens{% endblock %}

{% block content %}
<header class="page-header">
  <nav class="breadcrumbs" aria-label="Breadcrumb">
    <ol>
      <li><a href="/">Home</a></li>
      <li aria-current="page">Page Title</li>
    </ol>
  </nav>
  <h1>Page Title</h1>
  <p class="text-muted">Optional subtitle describing the page.</p>
</header>

<main id="main" class="grid-2">
  <section class="card">
    <h2 class="card-title">Section Title</h2>
    <!-- content -->
  </section>

  <section class="card">
    <h2 class="card-title">Another Section</h2>
    <!-- content -->
  </section>
</main>
{% endblock %}
```

---

## Screenshots with Playwright
Save as `scripts/screenshots.py` and run `python scripts/screenshots.py`.

```python
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

URLS = {
    "login": "http://localhost:8000/login",
    "home": "http://localhost:8000/",
    "story": "http://localhost:8000/story",
    "fixes": "http://localhost:8000/fixes",
    "reports": "http://localhost:8000/reports",
    "docs": "http://localhost:8000/docs",
    "audit": "http://localhost:8000/audit",
}

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 1024, "height": 768},
}

OUT_DIR = Path("docs/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

async def shoot(page, name, theme, viewport_key):
    await page.goto(URLS[name])
    await page.wait_for_load_state("networkidle")
    # set theme
    await page.evaluate(f"localStorage.setItem('rl-theme', '{theme}')")
    await page.reload(wait_until="networkidle")
    # wait for theme to apply
    await page.wait_for_timeout(200)
    file = OUT_DIR / f"{name}-{theme}.png"
    await page.screenshot(path=file, full_page=True)
    print(f"Saved {file}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for vp_name, vp in VIEWPORTS.items():
            context = await browser.new_context(viewport=vp)
            page = await context.new_page()
            for name in URLS:
                for theme in ("light", "dark"):
                    await shoot(page, name, theme, vp_name)
            await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

- Run the dev server first: `uvicorn app.main:app --reload`.
- Images are written to `docs/screenshots/` with names like `home-light.png` and `home-dark.png` (plus `home-tablet.png`).

---
