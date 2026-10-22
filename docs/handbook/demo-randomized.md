# Demo Randomization Details

RevenueLens’ demo environment does **not** always plant the full 8 × 8 leak set.  
Each fresh start (new Docker volume) generates a random mix of leaks so that the demo feels fresh while the evaluation suite remains deterministic.

## How the data are generated

1. **Seed handling**  
   * If `DEMO_SEED` is set, that integer is used as the random seed.  
   * Otherwise the entrypoint picks a random seed (`Demo seed: N` is printed in the logs).  

2. **Leak selection**  
   * From the 8 real check ids (`unrated_usage`, `rated_not_invoiced`, `tariff_mismatch`, `expired_discount`, `provisioned_not_billed`, `missed_renewal`, `unmatched_payment`, `duplicate_charge`) a random subset of **4‑8** types is chosen.  

3. **Instance count**  
   * For each chosen check a random count between **1‑8** is generated.  

4. **Customer choice**  
   * Record IDs are taken from randomly selected customers in the synthetic `nimbus` schema.

The generation code lives in `legacy_sim.generator.generate(seed, randomize=True)` and uses `random_leak_counts` to produce the per‑check counts.

## Pipeline

```
scripts/demo-entrypoint.sh
   └─ app.demo_pipeline seed/run
          ├─ legacy_sim.generator.generate(...)
          ├─ load data into Postgres
          └─ write /tmp/ground_truth.json
```

The pipeline also creates:

* 8 draft fixes (2 approved, 1 rejected, rest pending)  
* Audit entries (`demo_seeded`, `draft_created`, `fix_approved`, `fix_rejected`, `report_generated`)  
* Sample reports shown on the **Reports** page.

## Answer‑key grading

Implemented in `app/answer_key.py` → `compare()`:

* A **planted issue** is **matched** when a detection finding has the same `check` id **and** shares at least one `record_id` with the ground‑truth entry.  
* Findings that do not match any planted issue are counted as **false positives**.  
* Unmatched planted issues are counted as **false negatives**.  

The endpoint `GET /api/answer-key` returns JSON:

```json
{
  "seed": 12345,
  "planted_issues": [
    { "check": "tariff_mismatch", "record_ids": ["T987"], "matched": true, "leak_url": "/leaks/42" },
    …
  ],
  "summary": {
    "precision": 1.0,
    "recall": 1.0,
    "per_check": {
      "tariff_mismatch": { "tp": 3, "fp": 0, "fn": 0 },
      …
    }
  }
}
```

## Tests

* `tests/test_demo_randomized.py` verifies that different seeds produce different planted sets, that recall is **1.0** for seeds `7`, `123`, `2024`, and that the answer‑key endpoint returns the correct structure.  
* The login flow returns HTTP 422 for missing fields (validated in the same test suite).

## How to run the randomized demo

```bash
# Default random seed (printed in logs)
docker compose -f docker-compose.demo.yml up

# Reproduce a specific seed
DEMO_SEED=42 docker compose -f docker-compose.demo.yml up
```

* Resetting the stack (`docker compose -f docker-compose.demo.yml down -v`) clears the volume, causing a new random seed on the next `up`.  

## Why this matters

* Gives a more engaging demo each time.  
* Keeps the evaluation harness stable (seed 42, 8 instances per check).  
* Allows developers to verify that the grading logic correctly handles randomization and matches the ground truth.  

---  

*All data remains synthetic (Nimbus Telecom).*
