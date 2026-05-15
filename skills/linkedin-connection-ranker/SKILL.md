---
name: linkedin-connection-ranker
description: DEPRECATED — replaced by two focused skills. Use get-enriched-connections to download and enrich profiles, then rank-connections to rank them for a job.
---

# LinkedIn Connection Ranker (Deprecated)

This skill has been split into two focused skills:

1. **get-enriched-connections** — downloads LinkedIn Connections.csv, runs Apify enrichment, outputs `enriched_connections_YYYYMMDD.json`
2. **rank-connections** — takes the enriched JSON + a job URL, filters by location, ranks inline (no API key needed), outputs `ranked_connections_YYYYMMDD.json`

Use those skills instead. The original content is preserved below for reference only.

---

# Original Content

## Overview
The user works at a company and wants to refer connections to an open role there. Three-phase pipeline: filter Connections.csv to ≤1000 profession-matched candidates, enrich those profiles via Apify, then rank them with Claude — weighting both role fit AND length of relationship.

## Inputs Required
Ask the user for these before starting:
1. **Job posting URL** — the full URL of the job description
2. **Connections.csv path** — LinkedIn export (columns: `First Name, Last Name, URL, Email Address, Company, Position, Connected On`; actual data starts at row 4, rows 1–3 are LinkedIn notes)

If the user doesn't have the Connections.csv, **stop and show this exact guide:**

---
**How to export your LinkedIn connections (takes a few minutes + up to 24h waiting):**

1. Go to **https://www.linkedin.com** and log in
2. Click your **profile picture** (top right) → **Settings & Privacy**
3. In the left sidebar click **Data privacy**
4. Click **Download your data**
5. Select the **first option**: *"Download larger data archive, including connections, verifications, contacts, account history…"*
6. Click **Request archive**
7. LinkedIn will email you when it's ready — **can take up to 24 hours**
8. Open the email → click the download link
9. Extract the ZIP — inside you'll find **Connections.csv**

**Tip:** The ZIP contains many files (messages, profile, etc.) — only `Connections.csv` is needed.

Once you have the file, come back and provide the full path to it.

---

Do not proceed until the user confirms they have the file.

## Phase 0 — Apify Token Check

**Before doing anything else**, check for the token:

```python
import os
token = os.environ.get('APIFY_API_TOKEN')
```

If `token` is None or empty, **stop and show the user this exact guide:**

---
**You need an Apify API token. Here's exactly how to get one (free tier is enough):**

**Step 1 — Get the token:**
1. Go to **https://console.apify.com** → **Sign up**
2. Once logged in, click your **avatar** → **Settings** → **API & Integrations** tab
3. Under **Personal API tokens**, click the **copy icon** next to the default token

**Step 2 — Paste it in chat** and tell Claude to use it for this session.

**Step 3 — After the run is done, revoke it:**
Go back to Apify → **API & Integrations** → click **Delete** next to the token, then create a fresh one for next time.

Free tier gives ~$5/month. Scraping 1000 profiles costs ~$4 — enough for a single job referral run.

---

Do not proceed to Phase 1 until the token is confirmed.

## Phase 1 — Filter to ≤1000

**Goal:** Keep only connections with a profession that plausibly fits the job. This is a profession filter, not a quality filter — cast wide within the relevant field.

### 1a. Fetch job description
Use WebFetch on the job URL. Extract:
- Job title and close synonyms
- Required skills / tech stack
- Seniority level (IC, manager, director…)
- Department / function (engineering, sales, marketing…)

### 1b. Parse CSV
```python
import csv
from datetime import datetime

def load_connections(path):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    header_idx = next(i for i, l in enumerate(lines) if l.startswith('First Name'))
    reader = csv.DictReader(lines[header_idx:])
    rows = list(reader)
    # Parse connection age in days
    for r in rows:
        try:
            r['_days_connected'] = (datetime.today() - datetime.strptime(r['Connected On'], '%d %b %Y')).days
        except Exception:
            r['_days_connected'] = 0
    return rows
```

### 1c. Score & filter — profession-first
Build a keyword scorer on `Position` + `Company`. Keep top min(1000, total) by score. If ≤1000 total, keep all — but still compute scores for Phase 3.

```python
def score_phase1(row, title_keywords, skill_keywords, seniority_keywords):
    text = f"{row['Position']} {row['Company']}".lower()
    score = 0
    for kw in title_keywords:   score += 4 if kw in text else 0  # role match
    for kw in skill_keywords:   score += 2 if kw in text else 0  # skill match
    for kw in seniority_keywords: score += 1 if kw in text else 0
    return score
```

Discard anyone with score = 0 (completely unrelated profession). Save `filtered_connections_YYYYMMDD.csv`.

## Phase 2 — Enrich via Apify

**Actor:** `LpVuK3Zozwuipa5bp` (LinkedIn Profile Scraper)

### 2a. Run the actor
```python
import os, requests, time, json

APIFY_TOKEN = os.environ['APIFY_API_TOKEN']
ACTOR_ID    = 'LpVuK3Zozwuipa5bp'

profile_urls = [row['URL'] for row in filtered if row['URL']]

run = requests.post(
    f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs',
    params={'token': APIFY_TOKEN},
    json={
        'profileScraperMode': 'Profile details no email ($4 per 1k)',
        'queries': profile_urls   # field name verified from actor schema
    }
).json()

run_id = run['data']['id']
print(f'Apify run started: {run_id}')
```

### 2b. Poll for completion (runs take 5–30 min)
```python
while True:
    data = requests.get(
        f'https://api.apify.com/v2/actor-runs/{run_id}',
        params={'token': APIFY_TOKEN}
    ).json()['data']
    status = data['status']
    print(f'Status: {status}')
    if status in ('SUCCEEDED', 'FAILED', 'ABORTED'):
        break
    time.sleep(15)
```

### 2c. Download & store results
```python
from datetime import date
today = date.today().strftime('%Y%m%d')

dataset_id = requests.get(
    f'https://api.apify.com/v2/actor-runs/{run_id}',
    params={'token': APIFY_TOKEN}
).json()['data']['defaultDatasetId']

raw_profiles = requests.get(
    f'https://api.apify.com/v2/datasets/{dataset_id}/items',
    params={'token': APIFY_TOKEN, 'format': 'json'}
).json()

def slim_position(pos):
    return {
        'position':    pos.get('position'),
        'companyName': pos.get('companyName'),
        'duration':    pos.get('duration'),
        'startDate':   pos.get('startDate'),
        'endDate':     pos.get('endDate'),
        'description': pos.get('description'),
        'skills':      pos.get('skills'),
    }

def slim_profile(p):
    loc = p.get('location') or {}
    parsed = loc.get('parsed') or {}
    return {
        'originalQuery': p.get('originalQuery'),
        'linkedinUrl':   p.get('linkedinUrl'),
        'firstName':     p.get('firstName'),
        'lastName':      p.get('lastName'),
        'headline':      p.get('headline'),
        'openToWork':    p.get('openToWork'),
        'location': {
            'countryCode': loc.get('countryCode'),
            'city':        parsed.get('city'),
            'country':     parsed.get('country'),
            'text':        loc.get('linkedinText'),
        },
        'topSkills':       p.get('topSkills'),
        'about':           p.get('about'),
        'currentPosition': [slim_position(x) for x in (p.get('currentPosition') or [])],
        'experience':      [slim_position(x) for x in (p.get('experience') or [])],
        'education': [
            {'schoolName': e.get('schoolName'), 'degree': e.get('degree'), 'period': e.get('period')}
            for e in (p.get('profileTopEducation') or p.get('education') or [])
        ],
        'skills':    p.get('skills'),
        'languages': p.get('languages'),
    }

items = [slim_profile(p) for p in raw_profiles]

with open(f'enriched_profiles_{today}.json', 'w', encoding='utf-8') as f:
    json.dump(items, f, indent=2, ensure_ascii=False)

print(f'Saved {len(items)} slimmed profiles (~4KB each vs ~60KB raw)')
```

If Apify returns partial results, note missing URLs but continue.

## Phase 2.5 — Location Filter (in-person roles only)

**When to apply:** Check the job description. If the role is **in-person or hybrid** in a specific city, filter enriched profiles to only keep people currently located in that country/city. Skip this phase for fully remote roles.

The Connections.csv has no location field — this filter can only run after Apify enrichment.

Apify's `location` field is a dict (verified from live data):
```json
{
  "linkedinText": "Tel Aviv, Israel",
  "countryCode": "IL",
  "parsed": { "country": "Israel", "city": "Tel Aviv", "countryCode": "IL" }
}
```

```python
def is_in_location(profile, required_country_code, required_country_name):
    loc = profile.get('location')
    if not loc:
        return True  # unknown — keep, don't discard on missing data
    parsed = loc.get('parsed') or {}
    code  = (loc.get('countryCode') or parsed.get('countryCode') or '').upper()
    name  = (parsed.get('country') or parsed.get('countryFull') or loc.get('linkedinText') or '').lower()
    return code == required_country_code.upper() or required_country_name.lower() in name

# Example for Tel Aviv in-person role:
enriched_filtered = [p for p in items if is_in_location(p, 'IL', 'israel')]
print(f"After location filter: {len(enriched_filtered)} (was {len(items)})")
```

**Note:** `originalQuery` in the Apify response contains the LinkedIn URL that was submitted — use this for joining back to the CSV, not `linkedinUrl` (which may differ slightly).

```python
filtered_urls = {p.get('originalQuery', '').rstrip('/') for p in enriched_filtered}
filtered_for_ranking = [p for p in items if p.get('originalQuery', '').rstrip('/') in filtered_urls]
```

## Phase 3 — Rank with Claude

### Scoring formula

| Component | Weight | Source |
|-----------|--------|--------|
| LLM score (avg of 3 dimensions, 1–10) | 75% | Apify profile + job description |
| Relationship length bonus (1–10) | 25% | `Connected On` date from CSV |

**Three LLM dimensions — equal weight, all role-agnostic:**
- `requirements_match` — do they have the must-haves from the JD? (skills, tools, qualifications — whatever the role needs)
- `seniority_fit` — are they at the right level? (too junior or too senior both score low)
- `domain_fit` — have they worked in a similar industry/context to the hiring company?

**Relationship length bonus:**
```python
def relationship_bonus(days):
    if days >= 365 * 10: return 10   # 10+ years
    if days >= 365 * 5:  return 8    # 5–10 years
    if days >= 365 * 3:  return 5    # 3–5 years
    if days >= 365 * 1:  return 3    # 1–3 years
    return 1                          # < 1 year
```

**Combined score:**
```python
llm_score = round((r['requirements_match'] + r['seniority_fit'] + r['domain_fit']) / 3, 1)
final_score = round(llm_score * 0.75 + relationship_bonus * 0.25, 1)
```

### 3a. LLM ranking in batches of 50
```python
import anthropic, json

client = anthropic.Anthropic()

SYSTEM = """You are a talent scout helping someone refer connections to an open role.
Given a job description and LinkedIn profiles, score each profile on three dimensions (1-10 each).
Ignore relationship length — that is handled separately.

Dimensions:
- requirements_match: do they have the specific skills/qualifications this role requires?
- seniority_fit: are they at the right level (too junior OR too senior both score low)?
- domain_fit: have they worked in a similar industry or built similar products?

Return a JSON array — no extra text:
[{
  "url": "...",
  "requirements_match": 8,
  "seniority_fit": 7,
  "domain_fit": 6,
  "reason": "one sentence summary"
}]"""

def rank_batch(job_desc, profiles_batch):
    resp = client.messages.create(
        model='claude-opus-4-7',
        max_tokens=4096,
        system=SYSTEM,
        messages=[{
            'role': 'user',
            'content': f'Job description:\n{job_desc}\n\nProfiles:\n{json.dumps(profiles_batch)}'
        }]
    )
    return json.loads(resp.content[0].text)
```

### 3b. Merge, compute final score, output
```python
import csv

connection_lookup = {r['URL']: r['_days_connected'] for r in filtered}

ranked = []
for r in all_llm_results:
    days  = connection_lookup.get(r['url'], 0)
    bonus = relationship_bonus(days)
    llm   = round((r['requirements_match'] + r['seniority_fit'] + r['domain_fit']) / 3, 1)
    final = round(llm * 0.75 + bonus * 0.25, 1)
    ranked.append({**r, 'llm_score': llm, 'relationship_bonus': bonus,
                   'final_score': final, 'days_connected': days})

ranked.sort(key=lambda x: x['final_score'], reverse=True)

with open(f'ranked_connections_{today}.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'final_score', 'llm_score', 'requirements_match', 'seniority_fit', 'domain_fit',
        'relationship_bonus', 'days_connected', 'reason',
        'first_name', 'last_name', 'url', 'company', 'position', 'connected_on'
    ])
    writer.writeheader()
    writer.writerows(ranked)
```

## Output Files

| File | When created | Contents |
|------|-------------|----------|
| `filtered_connections_YYYYMMDD.csv` | After Phase 1 | ≤1000 profession-matched rows |
| `enriched_profiles_YYYYMMDD.json` | After Phase 2 | Full Apify profile objects |
| `ranked_connections_YYYYMMDD.csv` | After Phase 3 | Final ranked list with all score components |

All files written to the current working directory unless the user specifies otherwise.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| CSV rows 1-3 are LinkedIn notes, not data | Skip to the row starting with `First Name` |
| `Connected On` format is `24 Apr 2026` | Parse with `%d %b %Y` not `%Y-%m-%d` |
| Ranking all profiles in one LLM call | Batch ≤50 per call |
| Apify run takes 5–30 min for large lists | Poll every 15s, tell user to wait |
| Profiles missing from Apify results | LinkedIn blocks some; skip and note count |
| Including email in outputs | Omit `Email Address` from all output files |
| Scoring only on role fit | Final score MUST blend LLM fit + relationship length |

## Quick Checklist

- [ ] Confirmed `APIFY_API_TOKEN` — if missing, showed exact setup guide above
- [ ] Got job URL and CSV path from user
- [ ] Fetched and parsed job description
- [ ] Filtered CSV to profession-relevant rows, saved `filtered_connections_*.csv`
- [ ] Submitted Apify run, polled to completion, saved `enriched_profiles_*.json`
- [ ] Ranked in batches of 50 with Claude (3 dimensions: requirements_match, seniority_fit, domain_fit)
- [ ] Applied relationship length bonus and computed `final_score`
- [ ] Saved `ranked_connections_*.csv` with all score columns
- [ ] Printed top 20 to user inline
