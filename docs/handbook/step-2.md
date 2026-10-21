# Step 2 – The “Legacy” Billing Simulator – Interview Explainer  

## Why we built a fake legacy system  
* **Real‑world realism** – Most data‑quality interviews start with a legacy billing platform that has been patched, patched again, and never had a clean schema design.  By giving candidates a synthetic version that mimics those quirks we can test the same skills without exposing any proprietary data.  
* **Safety & reproducibility** – A completely artificial data set means no accidental leakage of a real customer’s usage or payment history, and it can be checked into source control.

## Why the tables look “legacy‑shaped” and have no foreign keys  
* Legacy telco systems were often built on early versions of PostgreSQL (or even on commercial RDBMSes) where developers relied on application logic rather than proper relational constraints.  
* Removing foreign keys creates the exact kind of dangling‑reference problems that cause many of the leaks we want candidates to find (e.g., a usage record that points to a non‑existent subscriber).  
* It also forces the interviewee to think about data integrity checks instead of simply trusting the DB engine.

## How the leaks are planted  
* Eight leak **types** are defined (unrated usage, rated‑not‑invoiced, tariff mismatch, expired discount, provisioned‑not‑billed, missed renewal, unmatched payment, duplicate charge).  
* For each type we pick a **distinct customer** (so the same customer never shows more than one problem).  
* The simulator writes the offending rows directly into the appropriate tables (e.g., a USG_CDR with a tariff code that does not exist in `RT_PLAN_CFG`).  
* The monetary impact for each leak is calculated from the simulated usage or payment amounts and stored in `ground_truth.json`.

## Why the generator is deterministic  
* The same seed is used every time the CLI runs, so the row counts, IDs, timestamps and monetary values are identical on every execution.  
* Determinism lets us ship a single “ground truth” file that can be used to automatically grade the candidate’s output – the oracle can compare the candidate’s detected leaks against the exact records we created.

## How the oracle proves everything  
* `legacy_sim/oracle.py` reads the database and the `ground_truth.json`.  
* It checks every planted leak is present (e.g., a usage record with `rated_flag = false` for the “unrated_usage” case) and that no other rows trigger the same rule.  
* If the candidate’s detection script reports the same set of record IDs and impacts, the oracle returns a perfect score; any deviation is reported as a mismatch.

## Typical interview Q&A  

| Question | Short Answer |
|----------|--------------|
| *Why not just give a clean schema with foreign keys?* | The point is to evaluate how candidates handle messy, real‑world data where integrity constraints are missing. |
| *Do the planted leaks reflect real telco problems?* | Yes – each type mirrors a known billing‑system defect (e.g., “tariff mismatch” is common after a price‑plan migration). |
| *Can I change the seed to get a different dataset?* | The CLI accepts `--seed` but the official interview runs with the default seed so the ground‑truth file matches. |
| *What should I return to the oracle?* | A JSON object mapping leak‑type → list of record IDs (or primary‑key values) and the total monetary impact per type. |
| *Is it okay to add my own helper tables?* | Yes, as long as you do not modify the existing legacy tables – the oracle only looks at those. |

Keep this explainer handy when you discuss the project with interviewers; it covers the “why” behind every design decision and prepares you for the most common follow‑up questions.  
