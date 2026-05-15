---
name: filter-connections
description: DEPRECATED — filtering is now built into rank-connections. Use rank-connections directly.
---

# Filter Connections (Deprecated)

This skill has been folded into **rank-connections**, which now handles all filtering internally:

1. **Location filter** — applied automatically from job description location
2. **Keyword filter** — matches headline, current title, and company against job keywords; keeps unknown/empty fields

Use the **rank-connections** skill directly. No separate filter step needed.

The original content is preserved below for reference only.

---

# Filter Connections

## Overview
Takes an enriched connections JSON file + a job URL, applies a location filter (if the role isn't fully remote), then runs a fast LLM pass to discard people with no plausible connection to the role. Errs on the side of keeping rather than discarding — the goal is to remove clear mismatches, not to pre-rank.

**Output:** `filtered_connections_YYYYMMDD.json` — subset of enriched profiles, each with a `_filter_reason` field explaining why they were kept.

---

## Step 0 — Get inputs

Ask the user for:
1. Path to `enriched_connections_YYYYMMDD.json` (from get-enriched-connections skill)
2. Job posting URL

---

## Step 1 — Fetch job description

Use WebFetch on the job URL. Extract and write down:
- Job title
- Required skills / tech stack
- Seniority level (IC, manager, director…)
- Location requirement (remote / hybrid / in-person + city/country)
- Company name and industry
- Any "nice to have" background or domain experience

---

## Step 2 — Load profiles and apply location filter

```python
import json

with open(ENRICHED_PATH, encoding='utf-8') as f:
    profiles = json.load(f)

print(f'Loaded {len(profiles)} enriched profiles')
```

If the role is **in-person or hybrid** in a specific city/country, filter by location first. Skip for fully remote roles.

```python
def is_in_location(p, country_code, country_name):
    loc = p.get('location') or {}
    code = (loc.get('countryCode') or '').upper()
    text = (loc.get('text') or loc.get('country') or '').lower()
    if not code and not text:
        return True  # unknown location — keep, don't discard on missing data
    return code == country_code.upper() or country_name.lower() in text

# Example: in-person role in Israel
location_filtered = [p for p in profiles if is_in_location(p, 'IL', 'israel')]
print(f'After location filter: {len(location_filtered)} profiles')
```

For fully remote: `location_filtered = profiles`

---

## Step 3 — Create batch files for LLM filtering pass

```python
import os

os.makedirs('_filter_batches', exist_ok=True)

def filter_slim(p):
    positions = list(filter(None, (p.get('currentPosition') or []) + (p.get('experience') or [])))
    skills = list(set((p.get('topSkills') or []) + (p.get('skills') or [])))
    return {
        'url':       p.get('url') or p.get('linkedinUrl'),
        'name':      f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
        'headline':  p.get('headline'),
        'positions': positions[:6],
        'skills':    skills[:12],
        'about':     (p.get('about') or '')[:200],
    }

batch_size = 50
batches = [location_filtered[i:i+batch_size] for i in range(0, len(location_filtered), batch_size)]

for idx, batch in enumerate(batches, 1):
    slim = [filter_slim(p) for p in batch]
    path = f'_filter_batches/batch_{idx:02d}.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(slim, f, indent=2, ensure_ascii=False)

print(f'Created {len(batches)} filter batch files')
```

---

## Step 4 — LLM filtering pass (keep / discard per profile)

**This is the key step.** Read each batch file and decide keep or discard for every profile. The bar is LOW — keep anyone who has *any* plausible relevance to the role: same industry, adjacent skills, relevant seniority, former colleague at a similar company, etc. Only discard people who have zero overlap with the job.

For each batch file:
1. Read `_filter_batches/batch_NN.json` with the Read tool
2. For every profile, output:

```json
{
  "url": "https://www.linkedin.com/in/...",
  "keep": true,
  "reason": "one sentence — why kept or discarded"
}
```

Append results to `filter_decisions` list. After all batches are processed, write to disk:

```python
with open('_filter_decisions_tmp.json', 'w', encoding='utf-8') as f:
    json.dump(filter_decisions, f, indent=2)
print(f'Filter decisions: {sum(1 for d in filter_decisions if d["keep"])} keep / {sum(1 for d in filter_decisions if not d["keep"])} discard')
```

---

## Step 5 — Build filtered output file

```python
from datetime import date

today = date.today().strftime('%Y%m%d')

# Build decision lookup by URL
keep_map = {}
reason_map = {}
for d in filter_decisions:
    url = (d.get('url') or '').rstrip('/')
    keep_map[url]   = d.get('keep', True)
    reason_map[url] = d.get('reason', '')

# Build profile lookup by URL
profile_lookup = {}
for p in location_filtered:
    url = (p.get('url') or p.get('linkedinUrl') or '').rstrip('/')
    if url:
        profile_lookup[url] = p

filtered = []
for url, keep in keep_map.items():
    if not keep:
        continue
    p = profile_lookup.get(url)
    if not p:
        continue
    out = dict(p)
    out['_filter_reason'] = reason_map.get(url, '')
    filtered.append(out)

with open(f'filtered_connections_{today}.json', 'w', encoding='utf-8') as f:
    json.dump(filtered, f, indent=2, ensure_ascii=False)

print(f'Saved filtered_connections_{today}.json — {len(filtered)} profiles kept from {len(location_filtered)}')
```

---

## Step 6 — Clean up temp files

```python
import shutil, os

shutil.rmtree('_filter_batches', ignore_errors=True)
if os.path.exists('_filter_decisions_tmp.json'):
    os.remove('_filter_decisions_tmp.json')
```

> WARNING: **NEVER touch `connections_annotations.json`** — this is golden data containing the user's familiarity ratings, recommendations, notes and outreach history. Do not delete, overwrite, or modify it at any point during this skill.

---

## Done

Tell the user:
- File saved: `filtered_connections_YYYYMMDD.json`
- How many kept vs total (e.g. "312 of 1000")
- What was filtered out (location, then irrelevant background)
- Next step: use the **rank-connections** skill with this file and the same job URL

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Being too aggressive — discarding anyone not obviously relevant | Err toward keeping. The ranking step handles fine-grained scoring. |
| Discarding unknown-location profiles | Keep them in the location filter — only exclude clear mismatches |
| URL mismatch in profile lookup | Strip trailing slashes on both sides of lookup |
| Processing all profiles in one LLM step | Always batch ≤50 per read — keeps each pass in context |
| Forgetting to write `_filter_decisions_tmp.json` | Write after all batches, before merge — so progress isn't lost if context resets |
