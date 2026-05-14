# LinkedIn CRM — New File Architecture & Skill Redesign

**Date:** 2026-05-13
**Status:** Approved for implementation

---

## 1. Problem

The current pipeline stores all enriched profile data in a single monolithic `enriched_connections_YYYYMMDD.json` file and user annotations in a separate `connections_annotations.json`. This causes:

- **Slow CRM load** — full work history for every person is loaded even though it's only needed on row expand
- **Fragile annotations** — stored in localStorage (lost on browser clear, can't be backed up)
- **No scale path** — 7000 connections × full profiles ≈ 84 MB, impractical to load
- **Redundant files** — two files that both need to be kept in sync

---

## 2. New File Architecture

```
LinkedIn connections scraper/
├── connections_index.json               ← lightweight display data + annotations
├── profiles/
│   ├── rom-gilad.json                   ← full profile, loaded only on row expand
│   └── ...
├── ranked_seniorengineer_20260513.json  ← scores only, one per role
├── scripts/
│   ├── enrich_connections.py            ← run by get-enriched-connections skill
│   └── rank_connections.py              ← run by rank-connections skill
├── connections_crm.html                 ← updated HTML (lazy-loads profiles)
└── crm_server.py                        ← updated server (new endpoints)
```

**Skills reference scripts, not inline code.** Skills contain orchestration instructions ("read `scripts/enrich_connections.py` and execute it step by step"), while the actual Python lives in versioned files in the repo. This keeps skills readable and makes scripts easy to edit without touching skill markdown.

### 2a. `connections_index.json`

URL-keyed map. Replaces both `enriched_connections_*.json` (display fields) and `connections_annotations.json` (annotation fields). Fully backward-compatible with existing annotation data — same URL key format, same annotation field names, adds display fields alongside.

```json
{
  "https://www.linkedin.com/in/rom-gilad": {
    "firstName": "Rom",
    "lastName": "Gilad",
    "headline": "VP Engineering at Wix",
    "location": "Tel Aviv, Israel",
    "currentTitle": "VP Engineering",
    "currentCompany": "Wix",
    "tenureInRole": "3y 1m",      ← from currentPosition[0].duration (Apify field)
    "daysConnected": 1240,
    "familiarity": "somewhat_familiar",
    "recommendation": "would_work_with",
    "notes": "",
    "outreach": { "reached_out": false, "date": "", "outcome": "" }
  }
}
```

**Annotation fields** start as `null`/`"not_familiar"`/`"na"` on creation. Preserved on re-enrichment (merge, never overwrite).

**Size estimate:** ~300 bytes/person × 7000 = ~2 MB. Fast to load, fast to POST on annotation change.

**Optional `_meta` key** (top-level, not a person entry):
```json
{
  "_meta": {
    "jobUrl": "https://...",
    "created": "2026-05-13",
    "totalInCsv": 7000,
    "enrichedCount": 850,
    "filtered": true
  }
}
```
Used when >1000 path was taken to carry the job URL through to ranking.

### 2b. `profiles/{handle}.json`

Handle extracted from LinkedIn URL: `linkedin.com/in/rom-gilad` → `profiles/rom-gilad.json`.

Contains full Apify-enriched data — only loaded when a CRM row is expanded or when ranking loads candidates that passed filtering.

```json
{
  "url": "https://www.linkedin.com/in/rom-gilad",
  "openToWork": false,
  "location": {
    "countryCode": "IL",
    "city": "Tel Aviv",
    "country": "Israel",
    "text": "Tel Aviv, Israel"
  },
  "about": "...",
  "currentPosition": [...],
  "experience": [...],
  "education": [...],
  "skills": [...],
  "topSkills": [...],
  "languages": [...]
}
```

**Size estimate:** ~5–15 KB/person. 1000 profiles = 5–15 MB on disk, but only fetched on demand.

### 2c. `ranked_{slug}_{date}.json`

Scores only — no profile data duplication. CRM joins to index by URL for display.

```json
{
  "_meta": {
    "roleName": "Senior Engineer @ Stripe",
    "jobUrl": "https://...",
    "created": "2026-05-13"
  },
  "rankings": [
    {
      "url": "https://www.linkedin.com/in/rom-gilad",
      "final_score": 8.2,
      "llm_score": 8.5,
      "requirements_match": 9,
      "seniority_fit": 8,
      "domain_fit": 8,
      "relationship_bonus": 8,
      "mobility_bonus": 10,
      "reason": "Led infra teams at scale, strong Node/React background"
    }
  ]
}
```

---

## 3. End-to-End Pipeline

```
Step 1: get-enriched-connections
  Input:  Connections.csv + Apify token
  ├─ CSV ≤ 1000 connections → enrich all
  └─ CSV > 1000 connections
       → ask for job URL
       → fetch job posting → extract title/skill keywords
       → filter CSV by Position + Company columns (keyword match, score > 0)
       → cap filtered set at 1000
       → warn user about Apify free tier ($5/mo ≈ 1250 profiles)
  → Submit to Apify → poll → download
  → Write connections_index.json (merge with existing — preserve annotations)
  → Write profiles/{handle}.json for each person
  → Save job URL to _meta if >1000 path was taken

Step 2: rank-connections
  Input:  job URL (from index _meta if already there, else ask) + role name
  → Fetch job description → extract keywords + location requirement
  → Load connections_index.json
  → Location filter: match index.location against job location (fast, no profile loads)
  → Keyword filter: match index.headline + currentTitle + currentCompany against job keywords (fast, no profile loads)
  → Load profiles/{handle}.json for candidates who passed both filters
  → LLM score in batches of 25 (3 dimensions: requirements_match, seniority_fit, domain_fit)
  → Compute finalScore = llmScore × 0.80 + relationshipBonus × 0.10 + mobilityBonus × 0.10
  → Write ranked_{slug}_{date}.json (scores + reason, no profile data)

Step 3: crm-connections
  → Open CRM in browser
  → Loads connections_index.json → populates table (All Connections tab)
  → Discovers ranked_*.json files → creates role tabs
  → Role tab: merges ranked scores with index data by URL
  → Row expand: fetches profiles/{handle}.json → shows full history/skills
  → Annotation change: debounced POST to /index → updates connections_index.json
```

---

## 4. Skill Changes

### 4a. `get-enriched-connections` — Major Rewrite

**Script:** `scripts/enrich_connections.py`

**Steps:**
0. Collect CSV path + Apify token (unchanged)
1. Load CSV, count rows
   - ≤ 1000: proceed with all, sort by tenure (most tenured first)
   - > 1000: ask for job URL → fetch → extract keywords → filter `Position` + `Company` columns → sort by tenure → cap at 1000 → warn about Apify cost
2. Submit to Apify (unchanged actor + params)
3. Poll until done (unchanged)
4. Download results
5. Build index entries (slim fields only) + profile files (full fields)
6. Merge with existing `connections_index.json` if present (preserve annotation fields, update display fields)
7. Write `connections_index.json` + all `profiles/{handle}.json` files
8. Remind user to revoke Apify token

**Filtering philosophy (>1000 path):** Err heavily on the side of keeping. Only discard rows with a `Position` that is clearly unrelated to the role's domain (e.g. ranking for engineers → discard "dentist", "primary school teacher"). Empty `Position` → always keep. Ambiguous → always keep. The goal is to reduce 7000 to a manageable number; quality filtering happens later in ranking.

**Keyword scoring for >1000 filter:**
```python
def score_csv_row(row, title_kws, skill_kws):
    text = f"{row['Position']} {row['Company']}".lower()
    if not text.strip():
        return 1  # empty title — keep, don't discard on missing data
    score = sum(4 for kw in title_kws if kw in text)
    score += sum(2 for kw in skill_kws if kw in text)
    return score
# Keep score >= 0 (i.e. only discard negative — use an explicit blocklist for clear mismatches)
# Actually: keep everyone with score > 0 OR empty title. Only hard-discard if score == 0 AND title is clearly unrelated.
```

In practice: extract broad keywords from the job (e.g. for a software role: "engineer", "developer", "software", "tech", "data", "product", "architect", "cto", "vp", "founder", "startup"). Keep any row that matches at least one OR has an empty/unknown title.

**Handle extraction:**
```python
import re
def handle_from_url(url):
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url or '')
    return m.group(1).rstrip('/') if m else None
```

**Index merge logic:**
```python
# Load existing index if present
existing = {}
if os.path.exists('connections_index.json'):
    with open('connections_index.json', encoding='utf-8') as f:
        existing = json.load(f)

# For each new profile: update display fields, preserve annotation fields
ANNOTATION_KEYS = {'familiarity', 'recommendation', 'notes', 'outreach'}
for url, new_entry in new_index.items():
    if url in existing:
        for k in ANNOTATION_KEYS:
            new_entry[k] = existing[url].get(k, new_entry[k])
    existing[url] = new_entry

# Preserve _meta
existing['_meta'] = new_meta
```

### 4b. `rank-connections` — Rewrite

**Script:** `scripts/rank_connections.py`

**Steps:**
0. Check `connections_index.json` for `_meta.jobUrl` — if present, use it and skip asking. Otherwise ask for job URL. Always ask for role name (short label for tab).
1. Fetch job description → extract: title keywords, skill keywords, location (city/country/remote flag)
2. Load `connections_index.json` (skip `_meta` key)
3. Location filter on index entries (existing logic, uses `index.location` text). Keep empty location.
4. Keyword filter on index entries — **inclusive bar**: match `headline + currentTitle + currentCompany` against title + skill keywords. Keep anyone who matches at least one keyword OR has empty/unknown fields. Only discard on clear evidence of no overlap. When in doubt, keep.
5. Load `profiles/{handle}.json` for each candidate that passed steps 3+4
6. Build ultra-slim ranking view from profile data (name, headline, last 3 positions, top 10 skills, about[:300])
7. Batch score in groups of 25: requirements_match, seniority_fit, domain_fit (1–10 each) + one-sentence reason
8. Compute finalScore:
   ```python
   llm_score = avg(requirements_match, seniority_fit, domain_fit)
   final_score = llm_score × 0.80 + relationship_bonus × 0.10 + mobility_bonus × 0.10
   ```
9. Sort by final_score descending
10. Write `ranked_{slug}_{date}.json` (scores + reason only, no profile duplication)
11. Print top 10 inline

**Relationship bonus** (based on `days_connected` from index):
- 10+ years → 10, 5–10y → 8, 3–5y → 5, 1–3y → 3, <1y → 1

**Mobility bonus** (based on `tenureInRole` from index — tenure in *current* role):
- < 1 year → 0 (just started, unlikely to move)
- 1–3 years → 5 (possible)
- 3–7 years → 10 (prime window for a move)
- 7+ years → 5 (settled, but not impossible)
- Unknown/empty → 5 (neutral, don't penalise missing data)

```python
def parse_tenure_years(s):
    """Parse '3y 1m', '2 yrs 4 mos', '10 months' → float years. Returns None if unparseable."""
    if not s: return None
    s = s.lower()
    y = re.search(r'(\d+)\s*y', s)
    m = re.search(r'(\d+)\s*mo', s)
    years = (int(y.group(1)) if y else 0) + (int(m.group(1)) / 12 if m else 0)
    return years if (y or m) else None

def mobility_bonus(tenure_str):
    yrs = parse_tenure_years(tenure_str)
    if yrs is None: return 5
    if yrs < 1:  return 0
    if yrs < 3:  return 5
    if yrs < 7:  return 10
    return 5
```

### 4c. `crm-connections` — Update

**Score display in expanded row (role tab):** Show all components — Final, Req., Seniority, Domain, Relationship, Mobility. Currently shows 5 components; add Mobility as 6th.

**Server changes:**
- Add `GET /index` → serves `connections_index.json`
- Add `POST /index` → writes `connections_index.json` (replaces `POST /annotations`)
- Add `GET /profiles/{handle}` → serves `profiles/{handle}.json` (validates handle is alphanumeric + hyphens, no `..`)
- Update `GET /manifest` → scans for `ranked_*.json` only (no longer looks for `enriched_*.json`)
- Remove `GET /annotations` + `POST /annotations`

**HTML/JS changes:**
- On load: fetch `/index` instead of `/annotations` + `/data/enriched_*.json`. Index contains both display data and annotations.
- Network tab: one tab "All Connections" sourced from index (no dated enriched files)
- Role tabs: load ranked file → merge with index by URL for display fields
- Row expand: `fetch('/profiles/' + handle)` → populate full history panel. Show loading state while fetching.
- Annotation save: POST to `/index` with full updated index (same debounce pattern)
- Handle extraction in JS: `url.match(/\/in\/([^/?#]+)/)?.[1]`
- Index iteration in JS: `Object.entries(index).filter(([k]) => k !== '_meta')` — always skip the `_meta` key

### 4d. `filter-connections` — Deprecate

Replace content with deprecation notice pointing to `rank-connections` (which now handles location + keyword filtering internally).

---

## 5. Migration

For users with existing data:

1. Run `get-enriched-connections` again → it detects existing `connections_annotations.json` OR existing `connections_index.json` and merges annotations into the new index. No annotation data lost.
2. Old `enriched_connections_*.json` files can be deleted after confirming CRM works.
3. Old `connections_annotations.json` can be deleted after confirming index contains all annotation data.

**Detection logic in get-enriched-connections:**
```python
# Check for old-style annotations file and merge if found
if os.path.exists('connections_annotations.json') and not os.path.exists('connections_index.json'):
    with open('connections_annotations.json', encoding='utf-8') as f:
        old_ann = json.load(f)
    # old_ann is already URL-keyed with same annotation fields — use as base
    existing = old_ann
```

---

## 6. Costs & Performance

| Operation | Cost | Time |
|---|---|---|
| Apify enrichment (1000 profiles) | ~$4 | 5–30 min |
| Rank 300 filtered profiles (Haiku) | ~$0.15 | 1–2 min |
| Rank 300 filtered profiles (Sonnet) | ~$0.50 | 2–4 min |
| CRM initial load (index only) | 0 | <1s for 7000 people |
| Row expand (one profile fetch) | 0 | <100ms |

---

## 7. Skills Not Affected

- `linkedin-connections-enricher` — different use case (company-wide DB), untouched
- `linkedin-connection-ranker` — already deprecated, no change
- `writing-hooks` — unrelated, untouched
