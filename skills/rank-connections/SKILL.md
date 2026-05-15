---
name: rank-connections
description: Use when ranking LinkedIn connections for a specific job opening. Triggers on: "rank my connections for this job", "who should I refer", "find best matches in my network", "rank connections". Requires connections_index.json and profiles/ folder (from get-enriched-connections skill).
---

# Rank Connections

## Overview
Filters connections from `connections_index.json` by location and job keywords, loads profile files for relevant candidates, scores them inline, and writes `ranked_{slug}_{date}.json` — a slim file with scores and reasons that the CRM auto-discovers as a new role tab.

**Script:** `skills/rank-connections/scripts/rank_connections.py` (run from your project root).

**Scoring formula:**
```
final_score = llm_score × 0.80 + relationship_bonus × 0.10 + mobility_bonus × 0.10
```
- `llm_score` — average of requirements_match, seniority_fit, domain_fit (1–10 each)
- `relationship_bonus` — how long connected (10+ yrs→10, 5–10→8, 3–5→5, 1–3→3, <1→1)
- `mobility_bonus` — tenure in current role (<1y→0, 1–3y→5, 3–7y→10, 7+y→5, unknown→5)

---

## Step 0 — Get inputs

1. **Job URL** — check `connections_index.json` for `_meta.jobUrl`. If present and non-empty, use it (it was captured during enrichment). Otherwise ask the user.
2. **Role name** — always ask: short label for the CRM tab (e.g. `"Senior Backend Engineer @ Stripe"`)

---

## Step 1 — Fetch job description

Use WebFetch on the job URL. Extract and record:
- Job title + synonyms
- Required skills / tech stack
- Seniority level
- Location requirement (remote / hybrid / in-person + city/country)
- Company name

Set variables:
- `KEYWORDS` = comma-separated title + skill keywords (broad — keep)
- `LOCATION` = city or country name, or `""` for remote roles

---

## Step 2 — Prepare batch files

```bash
python skills/rank-connections/scripts/rank_connections.py prepare \
    --keywords "KEYWORDS" \
    --location "LOCATION"
```

This filters the index (location first, then keywords — **keeping any unknown/empty fields**), loads profile files for filtered candidates, and writes batch files to `_rank_batches/`.

The script prints how many candidates passed each filter. Review the numbers — if fewer than ~20 candidates pass, the keywords may be too narrow. Consider broadening them and re-running.

---

## Step 3 — Score each batch inline

**This is the key step.** Read each `_rank_batches/batch_NN.json` file with the Read tool and score every profile.

For each batch file:
1. Read `_rank_batches/batch_NN.json`
2. For every profile, output scores + reason:

```json
{
  "url": "https://www.linkedin.com/in/...",
  "requirements_match": 8,
  "seniority_fit": 7,
  "domain_fit": 6,
  "reason": "one sentence — strongest signal for or against this person"
}
```

Score 1–10 on each dimension:
- `requirements_match` — do they have the specific skills/qualifications the role requires?
- `seniority_fit` — are they at the right level? (too junior AND too senior both score low)
- `domain_fit` — have they worked in a similar industry or built similar products?

Append all results to an `all_scores` list. After all batches are processed, write:

```python
import json
with open('_scores_tmp.json', 'w', encoding='utf-8') as f:
    json.dump(all_scores, f, indent=2)
print(f'Scored {len(all_scores)} profiles')
```

---

## Step 4 — Merge scores and write output

```bash
python skills/rank-connections/scripts/rank_connections.py merge \
    --scores _scores_tmp.json \
    --role-name "ROLE_NAME" \
    --job-url "JOB_URL"
```

This computes final scores (llm × 0.80 + relationship × 0.10 + mobility × 0.10), sorts by final score, writes `ranked_{slug}_{date}.json`, prints top 10, and cleans up temp files.

---

## Done

Tell the user:
- File saved: `ranked_{slug}_{date}.json`
- Top 10 from the merge output
- Refresh the CRM browser — new role tab appears automatically

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Fewer than 20 candidates after filtering | Keywords too narrow — broaden them in Step 2 |
| Scoring all batches in one step | Read and score one batch at a time — keeps each scoring pass in context |
| Forgetting to write `_scores_tmp.json` | Write after all batches scored — script cleans it up after merge |
| URL mismatch in merge | Script strips trailing slashes on both sides |
