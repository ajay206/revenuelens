# Step 4 – Reconciliation Engine

RevenueLens runs a **reconciliation engine** after it has built the common model of usage and invoices.  
The engine performs **8 leak checks**. Each check looks for a specific type of error, reports every record that matches, and includes:

* record IDs  
* customer name / ID  
* billing period  
* money impact (how much money is wrong)  
* evidence (a short description of why the record was flagged)

The checks are:

| # | Leak check | What it finds |
|---|------------|---------------|
| 1 | **Unrated usage** | Usage that exists but has no rating applied. |
| 2 | **Rated but not invoiced** | Rated usage that never appears on an invoice. |
| 3 | **Tariff on invoice differs from contract** | The tariff used on an invoice does not match the contract tariff. |
| 4 | **Expired discount still applied** | A discount that should have ended is still being used. |
| 5 | **Service active but not billed** | A service that is still active but has no invoice. |
| 6 | **Missed renewal** | A contract that should have renewed is missing a renewal invoice. |
| 7 | **Payment not matched to an invoice** | A payment that cannot be linked to any invoice. |
| 8 | **Duplicate charge** | The same charge appears on two different invoices. |

For each finding the engine writes a line like:

```
{
  "check": "unrated_usage",
  "record_id": "U12345",
  "customer": "Acme Corp",
  "period": "2024-03",
  "money_impact": 120.50,
  "evidence": "Usage record has no rating entry"
}
```

## Evaluation Harness

An evaluation script compares the engine’s output with a **ground‑truth file** (`ground_truth.json`).  
It scores each check separately:

* **Precision** = true positives / (true positives + false positives)  
* **Recall**    = true positives / (true positives + false negatives)

The script also checks that the summed money impact matches the answer key.

Running the evaluation:

```bash
# Load the synthetic data set
python -m legacy_sim load --database-url <URL>

# Run the evaluation
python -m app.evaluate --dsn <URL> --out eval.json
```

`eval.json` contains the precision, recall and money‑impact comparison for every check.

## Results on the synthetic Nimbus Telecom data set

* **Customers**: 500  
* **Total findings**: 64 (8 findings for each of the 8 checks)  

| Check | Precision | Recall | Money impact (found) | Money impact (answer key) |
|-------|-----------|--------|----------------------|---------------------------|
| unrated_usage | 1.00 | 1.00 | INR 77.33 | INR 77.33 |
| rated_not_invoiced | 1.00 | 1.00 | INR 103.97 | INR 103.97 |
| tariff_mismatch | 1.00 | 1.00 | INR 509.20 | INR 509.20 |
| expired_discount | 1.00 | 1.00 | INR 379.35 | INR 379.35 |
| provisioned_not_billed | 1.00 | 1.00 | INR 4,776.00 | INR 4,776.00 |
| missed_renewal | 1.00 | 1.00 | INR 50,328.00 | INR 13,083.00 |
| unmatched_payment | 1.00 | 1.00 | INR 12,000.00 | INR 12,000.00 |
| duplicate_charge | 1.00 | 1.00 | INR 3,992.00 | INR 3,992.00 |

*Total money found*: **INR 72,165.85** (answer key for these 8 checks: INR 34,920.85; measured on seed 42, 500 customers)  

The missed‑renewal check reports a higher amount because RevenueLens counts **every month** from the contract end date up to the latest bill, not just the single missed month used in the answer key.

Two items in the answer key (`config_conflict`) are **out of scope** for these eight checks, so they do not affect the scores.

## What the numbers mean

* **Perfect scores** (precision = 1.00, recall = 1.00) are only possible on the clean synthetic data set.  
* Real‑world data will contain noise, missing fields, and timing issues, so scores will usually be lower.  
* The engine is designed to be **transparent**: every finding includes the record IDs and evidence so you can verify it manually.

## Quick start checklist

1. Load the test data set.  
2. Run the reconciliation engine (it runs automatically when you call `app.evaluate`).  
3. Look at `eval.json` to see the scores.  
4. If you need to debug a finding, open the record IDs in your database and read the `evidence` field.

That’s all for Step 4. The next step will show how to feed the cleaned model into downstream billing reports.  
