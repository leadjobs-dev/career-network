---
name: rank-connections
description: 'Use when ranking LinkedIn connections for a specific job opening. Triggers on: "rank my connections for this job", "who should I refer", "find best matches in my network", "rank connections". Requires connections_index.json and profiles/ folder (from get-enriched-connections skill).'
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

## Step 0 — Fetch job description and run three-tier coverage check

**This step must happen before anything else — including asking for the role name.**

### 0a. Get job URL
Check `connections_index.json` for `_meta.jobUrl`. If present and non-empty, use it. Otherwise use the URL from the conversation.

### 0b. Fetch job description
Use WebFetch on the job URL. Extract:
- Job title + synonyms
- Required skills / tech stack
- Seniority level
- Location requirement (remote / hybrid / in-person + city/country)
- Company name

Set `LOCATION` = city or country name, or `""` for remote roles.

### 0c. Derive three keyword tiers from the job

Generate three keyword sets based on what you extracted:

| Tier | Strategy |
|------|----------|
| **Loose** | Broad role-type synonyms — catches the widest net, most noise |
| **Medium** | Specific tech stack + role type, no generic synonyms — balanced |
| **Tight** | Tech stack + seniority signals + domain-specific terms — fewest results, highest signal |

Example for a Senior Backend Engineer role at a payments company:
- **Loose**: `engineer,developer,software,backend,server,tech lead`
- **Medium**: `backend,node,python,ruby,java,golang,microservices,infrastructure,platform`
- **Tight**: `senior backend,lead backend,principal,staff engineer,node.js,python,golang,payments,financial,platform engineer`

### 0d. Run coverage for all three tiers

Run three coverage checks in sequence:

```bash
python skills/rank-connections/scripts/rank_connections.py coverage --csv data/Connections.csv --keywords "LOOSE_KEYWORDS"
python skills/rank-connections/scripts/rank_connections.py coverage --csv data/Connections.csv --keywords "MEDIUM_KEYWORDS"
python skills/rank-connections/scripts/rank_connections.py coverage --csv data/Connections.csv --keywords "TIGHT_KEYWORDS"
```

### 0e. Present results and ask user to pick

Show a combined table:

```
Keyword filter tiers:
  Loose:  X enriched, Y unenriched (~$Z to add all)
  Medium: X enriched, Y unenriched (~$Z to add all)
  Tight:  X enriched, Y unenriched (~$Z to add all)

For each tier, options are:
  a) Rank already-enriched only — free, instant, may miss people
  b) Enrich unenriched first (~$Z) — most complete

Which tier and option?
```

Also ask: **What should the CRM tab be called?** (e.g. `"Senior Backend Engineer @ HoneyBook"`)

- If user picks **rank only**: set `KEYWORDS` to chosen tier's keywords, proceed to Step 2.
- If user picks **enrich first**: run the enrichment script (see below), then proceed to Step 2.

**To enrich:**
```bash
python skills/get-enriched-connections/scripts/enrich_connections.py \
    --csv data/Connections.csv \
    --token "USER_TOKEN" \
    --keywords "CHOSEN_KEYWORDS" \
    --job-url "JOB_URL"
```
The user must provide the Apify token. Ask for it if not already given.

---

## Step 1 — Prepare batch files

Set variables (carried over from Step 0):
- `KEYWORDS` = chosen tier's keyword string
- `LOCATION` = city or country extracted from job description

---

## Step 2 — Prepare batch files

```bash
python skills/rank-connections/scripts/rank_connections.py prepare \
    --keywords "KEYWORDS" \
    --location "LOCATION"
```

This runs two filters in sequence:
1. **Location** — drops anyone outside the target city/country (keeps blank locations)
2. **Keyword** — drops anyone whose headline/title/company has none of the keywords (keeps blank headlines)

The script prints counts after each filter. Review — if fewer than ~20 pass the keyword filter, switch to a looser tier from Step 0.

---

## Step 3 — Score each batch inline (resumable)

**This is the key step.** Score one batch at a time and write scores to disk immediately — this makes the process resumable if context is compacted mid-run.

**Before starting**, check which batches are already scored:
```python
import glob; files = sorted(glob.glob('data/_scores_batch_*.json')); print('\n'.join(files) if files else 'none yet')
```
Skip any batch that already has a corresponding `_scores_batch_NN.json` file.

**For each unscored batch:**
1. Read `data/_rank_batches/batch_NN.json`
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

3. **Immediately after scoring the batch**, write scores to disk:

```python
import json
batch_scores = [/* scores for this batch */]
with open('data/_scores_batch_NN.json', 'w', encoding='utf-8') as f:
    json.dump(batch_scores, f, indent=2)
print(f'Wrote {len(batch_scores)} scores to data/_scores_batch_NN.json')
```

Repeat for every batch. Do not wait until all batches are done.

**After all batches are scored**, combine into `_scores_tmp.json`:

```python
import json, glob
all_scores = [s for f in sorted(glob.glob('data/_scores_batch_*.json')) for s in json.load(open(f, encoding='utf-8'))]
with open('data/_scores_tmp.json', 'w', encoding='utf-8') as f:
    json.dump(all_scores, f, indent=2)
print(f'Combined {len(all_scores)} scores to data/_scores_tmp.json')
```

---

## Step 4 — Merge scores and write output

```bash
python skills/rank-connections/scripts/rank_connections.py merge \
    --scores data/_scores_tmp.json \
    --role-name "ROLE_NAME" \
    --job-url "JOB_URL"
```

This computes final scores (llm × 0.80 + relationship × 0.10 + mobility × 0.10), sorts by final score, writes `ranked_{slug}_{date}.json`, prints top 10, and cleans up temp files (`_scores_tmp.json` and `_scores_batch_*.json`).

---

## Done

Tell the user:
- File saved: `ranked_{slug}_{date}.json`
- Top 10 from the merge output

Then automatically open the CRM: invoke the crm-connections skill.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Skipping coverage check and going straight to scoring | **Always run the three-tier coverage check first** — it's Step 0, before role name, before anything |
| Asking for role name before coverage check | Role name is asked at the end of Step 0e, alongside tier/enrichment choice |
| Jumping straight to prepare without enriching | If user picks enrich, run enrichment script and wait for it to finish before Step 2 |
| Fewer than 20 candidates after prepare filter | Keywords too narrow — switch to a looser tier from Step 0 |
| Scoring all batches in one step | Read and score one batch at a time — keeps each scoring pass in context |
| Forgetting to write per-batch score files | Write `_scores_batch_NN.json` immediately after each batch — do not accumulate in memory |
| Re-scoring batches that are already done | Check for existing `_scores_batch_*.json` before starting — skip those batches |
| Forgetting the combine step | Run the glob combine before merge — `_scores_tmp.json` is built from batch files |
| URL mismatch in merge | Script strips trailing slashes on both sides |
