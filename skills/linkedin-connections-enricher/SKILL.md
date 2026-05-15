---
name: linkedin-connections-enricher
description: Use when building a company-wide database of enriched LinkedIn connections. Takes one employee's Connections.csv, enriches the oldest 1000 connections via Apify, and outputs a standardized JSON ready for DB ingestion. No job filtering — this is a one-time bulk enrichment per employee.
---

# LinkedIn Connections Enricher

## Overview
One employee uploads their Connections.csv → get their oldest 1000 connections → enrich with full profile data via Apify → save standardized JSON for app/DB ingestion. Oldest-first because longer relationships = stronger referrals.

## Inputs Required
Ask for:
1. **Connections.csv path** — LinkedIn export (data starts at row 4; rows 1–3 are LinkedIn notes)
2. **Employee identifier** — name or email, used to tag records in the output (so the app knows which employee knows whom)
3. **Apify API token** — paste in chat, revoke on Apify after the session

If the user doesn't have the Connections.csv:

---
**How to export your LinkedIn connections:**
1. Go to **https://www.linkedin.com** → log in
2. Click your **profile picture** → **Settings & Privacy**
3. Left sidebar → **Data privacy** → **Download your data**
4. Select the **first option**: *"Download larger data archive, including connections…"*
5. Click **Request archive** — LinkedIn emails you when ready (up to 24h)
6. Extract the ZIP → find **Connections.csv**
---

## Phase 1 — Sort & Select Oldest 1000

No job filtering. Sort all connections by `Connected On` ascending (oldest first), take the first 1000.

```python
import csv
from datetime import datetime

def load_and_sort(path):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    header_idx = next(i for i, l in enumerate(lines) if l.startswith('First Name'))
    rows = list(csv.DictReader(lines[header_idx:]))
    for r in rows:
        try:
            r['_days_connected'] = (datetime.today() - datetime.strptime(r['Connected On'].strip(), '%d %b %Y')).days
        except Exception:
            r['_days_connected'] = 0
    # Oldest first
    rows.sort(key=lambda r: r['_days_connected'], reverse=True)
    selected = rows[:1000]
    print(f"Total connections: {len(rows)} → enriching oldest {len(selected)}")
    return selected
```

## Phase 2 — Enrich via Apify

**Actor:** `LpVuK3Zozwuipa5bp` — $4 per 1000 profiles (no email mode)

### 2a. Submit run
```python
import os, requests, time, json

APIFY_TOKEN = '<paste from user>'
ACTOR_ID    = 'LpVuK3Zozwuipa5bp'

profile_urls = [r['URL'].strip() for r in selected if r['URL'].strip()]

run = requests.post(
    f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs',
    params={'token': APIFY_TOKEN},
    json={
        'profileScraperMode': 'Profile details no email ($4 per 1k)',
        'queries': profile_urls
    }
).json()

run_id = run['data']['id']
print(f'Run started: {run_id}')
```

### 2b. Poll (5–30 min for 1000 profiles)
```python
while True:
    data = requests.get(
        f'https://api.apify.com/v2/actor-runs/{run_id}',
        params={'token': APIFY_TOKEN}
    ).json()['data']
    status = data['status']
    count  = data['stats'].get('outputDatasetItems', '?')
    print(f'Status: {status} | profiles done: {count}')
    if status in ('SUCCEEDED', 'FAILED', 'ABORTED'):
        break
    time.sleep(15)
```

### 2c. Download results
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

profiles = [slim_profile(p) for p in raw_profiles]
print(f'Downloaded and slimmed {len(profiles)} profiles (~4KB each vs ~60KB raw)')
```

## Phase 3 — Build Standardized Output

Merge Apify profile data with CSV metadata (days connected, employee tag). Output one JSON record per connection.

```python
# Build lookup: linkedin URL -> CSV row
csv_lookup = {}
for r in selected:
    url = r['URL'].strip().rstrip('/')
    csv_lookup[url] = r

EMPLOYEE_ID = '<employee name or email from user>'

records = []
for profile in profiles:
    # Apify may return url under different keys
    url = (profile.get('linkedinUrl') or profile.get('url') or '').rstrip('/')
    csv_row = csv_lookup.get(url, {})

    records.append({
        # Employee metadata
        'employee_id':     EMPLOYEE_ID,
        'days_connected':  csv_row.get('_days_connected', 0),
        'connected_on':    csv_row.get('Connected On', ''),

        # Identity
        'linkedin_url':    url,
        'first_name':      profile.get('firstName') or csv_row.get('First Name', ''),
        'last_name':       profile.get('lastName')  or csv_row.get('Last Name', ''),
        'full_name':       profile.get('fullName', ''),
        'headline':        profile.get('headline', ''),

        # Location
        'location':        profile.get('location') or profile.get('geoLocation', ''),
        'city':            profile.get('city', ''),
        'country':         profile.get('country', ''),

        # Current role
        'current_company': csv_row.get('Company', ''),
        'current_position':csv_row.get('Position', ''),

        # Enriched data
        'experience':      profile.get('experience', []),
        'education':       profile.get('education', []),
        'skills':          profile.get('skills', []),
        'summary':         profile.get('summary', ''),

        # Meta
        'enriched_at':     today,
        'apify_run_id':    run_id,
    })

out_path = f'enriched_{EMPLOYEE_ID.replace(" ","_")}_{today}.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(records, f, indent=2, ensure_ascii=False)

print(f'Saved {len(records)} records → {out_path}')
print(f'Missing from Apify: {len(selected) - len(profiles)} profiles (LinkedIn blocked or private)')
```

## Output Format

One JSON file per employee: `enriched_<employee>_YYYYMMDD.json`

Each record has a consistent schema so all employee files can be concatenated and loaded into the same DB table. Deduplicate by `linkedin_url` at ingestion time — if multiple employees know the same person, keep all rows (the `employee_id` + `days_connected` columns are the referral strength signal).

## Apify Token

Paste in chat → revoke on Apify after the session:
1. **https://console.apify.com** → avatar → **Settings** → **API & Integrations**
2. Copy the default token → paste here
3. After session: go back and click **Delete** on that token, create a fresh one next time

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Sorting newest-first | Must be ascending by `_days_connected` (oldest = highest days) |
| CSV rows 1–3 are notes | Skip to the row starting with `First Name` |
| `Connected On` format is `24 Apr 2026` | Parse with `%d %b %Y` |
| Using `profileUrls` as input key | Correct field is `queries` (verified from actor schema) |
| Deduplicating across employees at export time | Keep all rows per employee — the app deduplicates, not this skill |
| Storing email addresses | Omit `Email Address` from all outputs |

## Quick Checklist

- [ ] Got CSV path and employee identifier
- [ ] Got Apify token (paste in chat)
- [ ] Loaded CSV, sorted oldest-first, selected top 1000
- [ ] Submitted Apify run with `queries` field and no-email mode
- [ ] Polled to completion
- [ ] Downloaded profiles, merged with CSV metadata
- [ ] Saved `enriched_<employee>_YYYYMMDD.json`
- [ ] Reminded user to revoke the Apify token
