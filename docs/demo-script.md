# 5‑Minute Live Demo Script – Nimbus Synthetic Demo

**Goal:** Showcase RevenueLens end‑to‑end using the one‑command Docker demo.

---

## 1. Start the demo (0:00‑0:30)

```bash
curl -O https://raw.githubusercontent.com/ajay206/revenuelens/main/docker-compose.demo.yml
docker compose -f docker-compose.demo.yml up
```

* Wait for the “Health check passed” message in the terminal.
* Open **http://localhost:8000** in a browser.

---

## 2. Log in (0:30‑0:45)

* Email: **demo@revenuelens.local**
* Password: **revenuelens-demo**
* Click **Log in**.
* You should see a dashboard with a big number: **Total Revenue — $ …** and a badge *“Leaks detected: X”*.

---

## 3. View the leak list (0:45‑1:15)

* Click the **Leaks** navigation item.
* The table shows ~10 rows, each labelled “Leak – NMB_MAX_699 …”.
* Pick the first row – you’ll see a **Story** button.

---

## 4. Read a leak story (1:15‑2:00)

* Click **Story**.
* The modal displays:
  * A natural‑language description of the leak.
  * Citations linking to the offending invoices (synthetic IDs).
  * If you set a real LLM key, the text will be generated on‑the‑fly; otherwise a placeholder story appears.
* Highlight that the story is fully traceable back to raw data.

---

## 5. Draft & approve a fix (2:00‑2:45)

* In the story view, click **Create Fix**.
* A form pre‑populated with the suggested SQL `UPDATE` appears.
* Click **Submit** – the fix goes into the **Fix Queue**.
* Navigate to **Fixes → Queue**, locate the newly created entry and click **Approve**.
* A toast confirms “Fix applied”.

---

## 6. Audit log (2:45‑3:15)

* Click **Audit** (top‑right).
* Verify that the leak detection, story generation, and fix approval are recorded with timestamps and user (demo admin).

---

## 7. Generate reports (3:15‑3:45)

* Click **Reports**.
* Choose **CSV** or **PDF** – download the file.
* Open it: you’ll see a summary table of all leaks, actions taken, and remaining risk.

---

## 8. On‑demand documentation (3:45‑4:30)

* Click **Docs**.
* In the query box type: `document plan NMB_MAX_699`.
* Press **Enter** – a markdown document appears explaining the plan, its pricing, and the leak impact.
* Switch the **level** dropdown to **Engineer** – the doc becomes more technical (SQL snippets, schema details).

---

## 9. Wrap‑up (4:30‑5:00)

* Point out that all data is synthetic (Nimbus Telecom, ~500 customers, 64 planted leaks) – safe for demos.
* Mention that the same UI works on real data with a single line change of `DATABASE_URL`.
* Invite the audience to try the demo locally with the one‑liner at the top of the README.

*End of script.*
