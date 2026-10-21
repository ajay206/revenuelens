# Step 3 – Connect, Discover, Map, Learn, and Replay

RevenueLens must understand a billing database it has never seen before.  
Step 3 does all of that automatically.

---

## 1. Connect in read‑only mode  

```bash
python -m legacy_sim load --database-url <URL>
```  

The command opens the target database with a read‑only user.  
No data is changed.

---

## 2. Discover the schema  

The discovery module (`app/discovery.py`) scans the database:

* Lists every table.
* Lists every column in each table.
* Detects primary keys, foreign keys and candidate join columns.
* Builds a graph of possible joins.

For the Nimbus Telecom test data it found:

| Tables | Joins |
|--------|-------|
| 13     | 22    |

---

## 3. Map to the common RevenueLens model  

Mapping (`app/mapping.py`) tries to fit the discovered schema to the standard model (customer, product, usage, invoice, etc.).

* **Heuristics first** – column names, data types, and key patterns give an initial guess.
* **Low‑confidence fields** are sent to a free LLM (`app/llm.py`).  
  The model only refines fields it is unsure about, keeping cost low.
* A human reviewer checks the suggested mappings and approves or edits them.

The result is a JSON map that tells the rest of the system where to find each required piece of information.

---

## 4. Learn plans, rates, and discounts  

Learning (`app/learning.py`) looks at two places:

1. **Configuration tables** – tables that list plans, rates, discount rules, etc.  
2. **Historical billed data** – existing invoices that already contain calculated amounts.

For every rule it extracts a **source tag** that records whether the rule came from config or from observed invoices.  
On the synthetic data it learned **50 rules** (prices, tier thresholds, discount formulas, etc.).

---

## 5. Replay past bills to prove understanding  

Replaying (`app/replay.py`) runs the newly built model against all historic invoices:

```bash
python -m app.onboard --dsn <URL> --schema nimbus --out report.json
```

The replay engine:

1. Generates a bill for each historic invoice using the learned rules.  
2. Compares the generated total to the stored total.  
3. Records matches, mismatches, and the reason for each mismatch.

Results on the Nimbus Telecom dataset:

* **Invoices checked:** 2 244  
* **Exact matches:** 2 189 (97.55 %)  
* **Mismatches:** 55 – these are the deliberately planted leaks that Step 4 will identify.

The `report.json` file contains the match rate, a list of mismatched invoice IDs, and the rule that caused each difference.

---

## 6. How to run Step 3 end‑to‑end  

```bash
# Load the sample database (read‑only)
python -m legacy_sim load --database-url <URL>

# Run the onboarding pipeline for schema "nimbus"
python -m app.onboard --dsn <URL> --schema nimbus --out report.json
```

Check `report.json` for the match percentage and any mismatches.

---

## 7. Known limits  

* The **plan‑fee conflict** that is intentionally placed in the config is not flagged yet.  
* Tickets and wiki pages are discovered later in **Step 8**.  

These will be addressed in later steps.

---  

That is all you need to run and understand Step 3.  
