# 5‑Minute Live Demo Script – Nimbus Synthetic Demo

**Goal:** Showcase RevenueLens end‑to‑end using the one‑command Docker demo.

---

## 1. Start the demo (0:00‑0:30)

```bash
curl -O https://raw.githubusercontent.com/ajay206/revenuelens/main/docker-compose.demo.yml
docker compose -f docker-compose.demo.yml up
```

* Wait for the “Health check passed” message in the terminal.  
* Open **http://localhost:8765** in a browser.  
* (Optional) Override the port: `DEMO_PORT=9123 docker compose -f docker-compose.demo.yml up`.

---

## 2. Log in (0:30‑0:45)

* Email: **demo@revenuelens.local**  
* Password: **revenuelens-demo**  
* Click **Log in**.  
* Friendly error messages appear for empty fields or wrong password. The sign‑in button is disabled while the request is in flight.

---

## 3. View the leak list (0:45‑1:15)

* Click the **Leaks** navigation item.  
* The table shows a random number of rows (4‑8 leak types, 1‑8 instances each).  
* Pick any row – you’ll see a **Story** button.

---

## 4. Read a leak story (1:15‑2:00)

* Click **Story**.  
* The modal displays a natural‑language description, citations to synthetic invoices, and a **Planted issues** link that points to the `/planted` page showing the ground‑truth entry for this leak.

---

## 5. Draft & approve a fix (2:00‑2:45)

* In the story view, click **Create Fix**.  
* A form pre‑populated with the suggested SQL `UPDATE` appears.  
* Click **Submit** – the fix goes into the **Fix Queue**.  
* Navigate to **Fixes → Queue**, locate the newly created entry and click **Approve**.  
* A toast confirms “Fix applied”. (Two other fixes are already approved, one is rejected, the rest pending.)

---

## 6. Audit log (2:45‑3:15)

* Click **Audit** (top‑right).  
* Verify entries such as `demo_seeded`, `draft_created`, `fix_approved`, `report_generated` with timestamps and the demo user.

---

## 7. Generate reports (3:15‑3:45)

* Click **Reports**.  
* Choose **CSV** or **PDF** – download the file.  
* Opening it shows a summary of all leaks, actions taken, and remaining risk. The download action is recorded in the audit trail.

---

## 8. On‑demand documentation (3:45‑4:30)

* Click **Docs**.  
* In the query box type: `document plan NMB_MAX_699`.  
* Press **Enter** – a markdown document appears explaining the plan, its pricing, and the leak impact.  
* Switch the **level** dropdown to **Engineer** – the doc becomes more technical (SQL snippets, schema details).

---

## 9. Planted issues page (4:30‑4:45)

* Navigate to **Planted issues (demo)** via the sidebar or directly to `/planted`.  
* The page lists every planted leak, its check id, match status, and a link back to the leak record.  
* Verify that all planted leaks are marked **Matched**.

---

## 10. Reproduce the same random seed (4:45‑5:00)

* The demo logs show `Demo seed: N`.  
* To reproduce, stop the stack, then start it again with: <br>`DEMO_SEED=N docker compose -f docker-compose.demo.yml up`.  
* The same set of leaks and fixes will appear.

*End of script.*
