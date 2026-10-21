Step 5 – Explain Findings Handbook
===================================

### What the explainer does
The **explainer** takes the deterministic findings produced by the
reconciliation step and turns them into a human‑readable story.  For every
`Finding` it:

1. Calculates a stable *money impact* (absolute value of the impact field).
2. Builds a list of citations that point to the underlying database records
   (`record` citations) **and** to any recent tickets that match the problem
   domain (ticket citations).
3. Matches the finding’s `check` name to a ticket‑keyword using the
   `_CHECK_TO_TICKET_KEY` map (e.g. `unrated_usage` → `rating`).
4. Calls a language‑model LLM to generate the narrative fields
   (`title`, `what`, `since_when`, `root_cause`, `who_affected`, `what_to_do`).

Only the narrative is supplied by the LLM – the impact and citations are
always computed locally so the result is reproducible.

### How to run it

```bash
python -m app.explain \\
    --database-url postgresql://user:pass@host/db \\
    --schema nimbus \\
    --out stories.md          # markdown output file
    [--limit N]               # optional limit on number of findings
```

The command discovers the schema, runs the reconciliation checks,
loads a deterministic set of tickets from the legacy simulator and then
writes two files:

* `stories.md` – a markdown document that can be sent to stakeholders.
* `stories.json` – a machine‑readable representation of the same stories.

### Runtime free models

| Provider | Model | Notes |
|----------|-------|-------|
| **Groq** | `gpt-oss-120b` | Free tier, low‑effort, high‑capacity. |
| **OpenRouter** | `nemotron` | Free tier, suitable fallback. |
| **Google Gemini** | `flash‑lite` | Free tier, fast response. |
| **CI fallback** | `fake` (environment variable `RL_LLM=fake`) | Used in the test suite so no external calls are made. |

The helper `app.llm.free_llm_from_env()` selects the first available model
in the order above.  In continuous‑integration environments the `RL_LLM`
environment variable is set to `fake`, guaranteeing that no real LLM is
invoked.

### Guarantees

* **Money impact** – always the absolute value of `Finding.impact`
  (rounded to two decimals).  The LLM cannot override this field.
* **Citations** – every record ID in the finding and every ticket that
  matches the check are added.  This ensures the story can be traced back
  to the source data.
* **No AI‑generated money or citations** – all monetary numbers and
  citation references are derived from the code, never from the LLM.

### Limitations

* The narrative quality depends on the chosen LLM; the fallback `fake`
  model only returns the static templates used in the unit tests.
* Ticket matching is simple keyword‑based and may miss relevant tickets
  if they use different terminology.
* The explainer does not attempt to validate the LLM’s JSON – malformed
  responses are safely ignored and the deterministic templates are used
  instead, which lowers the confidence flag to *needs confirmation*.
