# CRM Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic enriched JSON + localStorage annotations with a 3-layer file architecture (index + per-person profiles + slim ranked files), add a mobility score component, and make skills reference Python scripts instead of inline code.

**Architecture:** `connections_index.json` (URL-keyed map, display + annotations, ~2MB for 7k people) replaces both old enriched and annotations files. `profiles/{handle}.json` files hold full profile data loaded only on demand. `ranked_{slug}_{date}.json` holds scores only. Two Python scripts handle all data processing; skills orchestrate them.

**Tech Stack:** Python 3.8+ stdlib + requests, vanilla JS, Python http.server

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `scripts/enrich_connections.py` | **Create** | CSV parse, Apify submit/poll/download, write index + profiles/ |
| `scripts/rank_connections.py` | **Create** | Filter index, load profiles, build batch files, merge LLM scores |
| `tests/test_enrich.py` | **Create** | Unit tests for pure functions in enrich_connections.py |
| `tests/test_rank.py` | **Create** | Unit tests for pure functions in rank_connections.py |
| `crm_server.py` | **Modify** | Add /index, /profiles/{handle} endpoints; remove /annotations |
| `connections_crm.html` | **Modify** | Load from /index, lazy-fetch profiles on expand, add mobility score |
| `skills/get-enriched-connections/SKILL.md` | **Rewrite** | Orchestration instructions referencing enrich_connections.py |
| `skills/rank-connections/SKILL.md` | **Rewrite** | Orchestration instructions referencing rank_connections.py |
| `skills/crm-connections/SKILL.md` | **Update** | Embed updated crm_server.py + connections_crm.html templates |
| `skills/filter-connections/SKILL.md` | **Deprecate** | Replace with deprecation notice |

**Execution order:** Tasks 1→2→3→4 are the data pipeline. Tasks 5→6 are the CRM. Tasks 7→8→9→10 are skill updates. Tasks 5–10 can start after Task 1 (index format is defined there).

---

## Task 1: Create `tests/test_enrich.py` and `scripts/enrich_connections.py`

**Files:**
- Create: `tests/test_enrich.py`
- Create: `scripts/enrich_connections.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_enrich.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from enrich_connections import (
    handle_from_url, score_csv_row, filter_rows,
    get_location_text, get_current_title_company, get_tenure_in_role,
    build_index_entry, slim_position,
)

# --- handle_from_url ---
def test_handle_from_url_standard():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad') == 'rom-gilad'

def test_handle_from_url_trailing_slash():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad/') == 'rom-gilad'

def test_handle_from_url_with_params():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad?mini=true') == 'rom-gilad'

def test_handle_from_url_none():
    assert handle_from_url(None) is None

def test_handle_from_url_non_linkedin():
    assert handle_from_url('https://example.com') is None

# --- score_csv_row ---
def test_score_csv_row_match():
    row = {'Position': 'Senior Software Engineer', 'Company': 'Google'}
    assert score_csv_row(row, ['engineer', 'developer']) > 0

def test_score_csv_row_no_match():
    row = {'Position': 'Primary School Teacher', 'Company': 'Springfield Elementary'}
    assert score_csv_row(row, ['engineer', 'developer', 'software']) == 0

def test_score_csv_row_empty_position():
    row = {'Position': '', 'Company': ''}
    # empty title → always keep (returns 1)
    assert score_csv_row(row, ['engineer']) == 1

def test_score_csv_row_case_insensitive():
    row = {'Position': 'ENGINEER', 'Company': ''}
    assert score_csv_row(row, ['engineer']) > 0

# --- filter_rows ---
def test_filter_rows_keeps_matches():
    rows = [
        {'Position': 'Software Engineer', 'Company': 'Acme'},
        {'Position': 'Dentist', 'Company': 'Clinic'},
        {'Position': '', 'Company': ''},  # empty — always keep
    ]
    result = filter_rows(rows, ['engineer', 'developer'])
    assert len(result) == 2
    assert rows[1] not in result

def test_filter_rows_no_keywords_keeps_all():
    rows = [{'Position': 'Dentist', 'Company': 'X'}, {'Position': 'Engineer', 'Company': 'Y'}]
    assert filter_rows(rows, []) == rows

# --- get_location_text ---
def test_get_location_text_city_country():
    profile = {'location': {'parsed': {'city': 'Tel Aviv', 'country': 'Israel'}, 'linkedinText': 'Tel Aviv, Israel'}}
    assert get_location_text(profile) == 'Tel Aviv, Israel'

def test_get_location_text_empty():
    assert get_location_text({}) == ''

# --- get_current_title_company ---
def test_get_current_title_company_from_position():
    profile = {'currentPosition': [{'title': 'VP Engineering', 'companyName': 'Wix'}]}
    title, company = get_current_title_company(profile)
    assert title == 'VP Engineering'
    assert company == 'Wix'

def test_get_current_title_company_empty():
    title, company = get_current_title_company({})
    assert title == ''
    assert company == ''

# --- get_tenure_in_role ---
def test_get_tenure_in_role():
    profile = {'currentPosition': [{'duration': '3y 1m'}]}
    assert get_tenure_in_role(profile) == '3y 1m'

def test_get_tenure_in_role_empty():
    assert get_tenure_in_role({}) == ''

# --- build_index_entry ---
def test_build_index_entry_annotations_default():
    profile = {
        'firstName': 'Rom', 'lastName': 'Gilad', 'headline': 'VP Eng',
        'location': {}, 'currentPosition': [], 'experience': [],
    }
    csv_row = {'First Name': 'Rom', 'Last Name': 'Gilad', '_days_connected': 500}
    entry = build_index_entry(profile, csv_row)
    assert entry['familiarity'] == 'not_familiar'
    assert entry['recommendation'] == 'na'
    assert entry['notes'] == ''
    assert entry['daysConnected'] == 500

# --- slim_position ---
def test_slim_position_dict():
    p = {'title': 'Engineer', 'companyName': 'Acme', 'duration': '2y'}
    assert slim_position(p) == 'Engineer at Acme (2y)'

def test_slim_position_string():
    assert slim_position('Some position') == 'Some position'

def test_slim_position_none():
    assert slim_position(None) is None
```

- [ ] **Step 2: Run tests to confirm they all fail**

```
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python -m pytest tests/test_enrich.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'enrich_connections'`

- [ ] **Step 3: Create `scripts/__init__.py`**

Create an empty file `scripts/__init__.py` (makes the scripts directory a package for imports).

- [ ] **Step 4: Write `scripts/enrich_connections.py`**

Create `scripts/enrich_connections.py`:

```python
#!/usr/bin/env python3
"""
LinkedIn connections enrichment pipeline.

Usage (< 1000 connections):
    python scripts/enrich_connections.py --csv Connections.csv --token apify_XXX

Usage (> 1000 connections, pre-filter by job keywords):
    python scripts/enrich_connections.py --csv Connections.csv --token apify_XXX \
        --keywords "engineer,developer,backend,cto,tech lead" --job-url "https://..."

Outputs:
    connections_index.json   — URL-keyed map: display fields + blank annotation fields
    profiles/{handle}.json   — one file per person, full Apify data
"""
import argparse, csv, json, os, re, time
from datetime import datetime, date


# ── CSV parsing ──────────────────────────────────────────────────────────────

def load_connections(csv_path):
    """Parse LinkedIn Connections.csv. Rows 1-3 are LinkedIn notes; find real header."""
    with open(csv_path, encoding='utf-8') as f:
        lines = f.readlines()
    header_idx = next(i for i, l in enumerate(lines) if l.startswith('First Name'))
    rows = list(csv.DictReader(lines[header_idx:]))
    for r in rows:
        try:
            r['_days_connected'] = (
                datetime.today() - datetime.strptime(r['Connected On'].strip(), '%d %b %Y')
            ).days
        except Exception:
            r['_days_connected'] = 0
    return rows


# ── Pre-filter for > 1000 connections ────────────────────────────────────────

def score_csv_row(row, keywords):
    """Score a CSV row against keywords. Empty title returns 1 (always keep)."""
    text = f"{row.get('Position', '')} {row.get('Company', '')}".lower().strip()
    if not text:
        return 1  # unknown title — keep, don't penalise missing data
    return sum(1 for kw in keywords if kw.lower() in text)


def filter_rows(rows, keywords):
    """Keep rows matching any keyword OR with empty title. Only discard clear mismatches."""
    if not keywords:
        return rows
    return [r for r in rows if score_csv_row(r, keywords) > 0]


# ── Handle extraction ─────────────────────────────────────────────────────────

def handle_from_url(url):
    """Extract LinkedIn handle from URL: linkedin.com/in/rom-gilad → 'rom-gilad'"""
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url or '')
    return m.group(1).rstrip('/') if m else None


# ── Profile field helpers ─────────────────────────────────────────────────────

def slim_position(p):
    """Convert Apify position dict or string to a readable string."""
    if not p:
        return None
    if isinstance(p, str):
        return p.strip() or None
    title = p.get('title') or p.get('position') or ''
    company = p.get('companyName') or ''
    dur = p.get('duration') or ''
    if title and company:
        base = f'{title} at {company}'
    else:
        base = title or company
    return (f'{base} ({dur})' if dur else base).strip() or None


def get_url(profile):
    """Extract the submitted URL from an Apify profile response."""
    oq = profile.get('originalQuery')
    if isinstance(oq, dict):
        url = oq.get('query', '')
    else:
        url = oq or ''
    return (url or profile.get('linkedinUrl') or '').rstrip('/')


def get_current_title_company(profile):
    """Return (title, company) from currentPosition[0], or ('', '') if missing."""
    pos = profile.get('currentPosition') or []
    if pos:
        p = pos[0]
        return (p.get('title') or p.get('position') or ''), (p.get('companyName') or '')
    return '', ''


def get_tenure_in_role(profile):
    """Return duration string for current role, e.g. '3y 1m'. Empty string if missing."""
    pos = profile.get('currentPosition') or []
    return pos[0].get('duration') or '' if pos else ''


def get_location_text(profile):
    """Return human-readable location string from Apify location field."""
    loc = profile.get('location') or {}
    parsed = loc.get('parsed') or {}
    city = parsed.get('city') or ''
    country = parsed.get('country') or ''
    text = loc.get('linkedinText') or ''
    if city and country:
        return f'{city}, {country}'
    return text or country or ''


# ── Index + profile file builders ─────────────────────────────────────────────

ANNOTATION_KEYS = {'familiarity', 'recommendation', 'notes', 'outreach'}
_ANNOTATION_DEFAULTS = {
    'familiarity': 'not_familiar',
    'recommendation': 'na',
    'notes': '',
    'outreach': {'reached_out': False, 'date': '', 'outcome': ''},
}


def build_index_entry(profile, csv_row):
    """Build a lightweight index entry. Annotation fields start at defaults."""
    title, company = get_current_title_company(profile)
    return {
        'firstName':     profile.get('firstName') or csv_row.get('First Name', ''),
        'lastName':      profile.get('lastName')  or csv_row.get('Last Name', ''),
        'headline':      profile.get('headline', ''),
        'location':      get_location_text(profile),
        'currentTitle':  title,
        'currentCompany': company,
        'tenureInRole':  get_tenure_in_role(profile),
        'daysConnected': csv_row.get('_days_connected', 0),
        **_ANNOTATION_DEFAULTS,
    }


def build_profile_file(profile):
    """Build the full profile JSON stored in profiles/{handle}.json."""
    loc = profile.get('location') or {}
    parsed = loc.get('parsed') or {}
    return {
        'url':      get_url(profile),
        'openToWork': profile.get('openToWork'),
        'location': {
            'countryCode': loc.get('countryCode'),
            'city':        parsed.get('city'),
            'country':     parsed.get('country'),
            'text':        loc.get('linkedinText'),
        },
        'about':          (profile.get('about') or '')[:500],
        'currentPosition': profile.get('currentPosition') or [],
        'experience':      (profile.get('experience') or [])[:10],
        'education': [
            {'school': e.get('schoolName'), 'degree': e.get('degreeName') or e.get('degree')}
            for e in (profile.get('profileTopEducation') or profile.get('education') or [])[:3]
        ],
        'skills':    (profile.get('skills') or [])[:20],
        'topSkills': (profile.get('topSkills') or [])[:10],
        'languages': profile.get('languages') or [],
    }


# ── Index merge ───────────────────────────────────────────────────────────────

def merge_index(new_entries, index_path):
    """
    Merge new index entries with existing data.
    Preserves annotation fields from existing entries.
    Also migrates old-style connections_annotations.json if present.
    """
    existing = {}
    if os.path.exists(index_path):
        with open(index_path, encoding='utf-8') as f:
            existing = json.load(f)
    elif os.path.exists('connections_annotations.json'):
        # Migrate old-style annotations file
        with open('connections_annotations.json', encoding='utf-8') as f:
            existing = json.load(f)
        print('Migrating connections_annotations.json → connections_index.json')

    merged = dict(existing)
    for url, new_entry in new_entries.items():
        if url in existing:
            for k in ANNOTATION_KEYS:
                if k in existing[url]:
                    new_entry[k] = existing[url][k]
        merged[url] = new_entry
    return merged


# ── Apify API ─────────────────────────────────────────────────────────────────

ACTOR_ID = 'LpVuK3Zozwuipa5bp'


def submit_apify_run(token, profile_urls):
    import requests
    run = requests.post(
        f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs',
        params={'token': token},
        json={
            'profileScraperMode': 'Profile details no email ($4 per 1k)',
            'queries': profile_urls,
        }
    ).json()
    return run['data']['id']


def poll_apify_run(token, run_id):
    import requests
    while True:
        data = requests.get(
            f'https://api.apify.com/v2/actor-runs/{run_id}',
            params={'token': token}
        ).json()['data']
        status = data['status']
        count = data['stats'].get('outputDatasetItems', '?')
        print(f'  Status: {status} | profiles done: {count}')
        if status in ('SUCCEEDED', 'FAILED', 'ABORTED'):
            return status, data['defaultDatasetId']
        time.sleep(15)


def download_apify_results(token, dataset_id):
    import requests
    return requests.get(
        f'https://api.apify.com/v2/datasets/{dataset_id}/items',
        params={'token': token, 'format': 'json'}
    ).json()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Enrich LinkedIn connections via Apify.')
    parser.add_argument('--csv',        required=True,  help='Path to Connections.csv')
    parser.add_argument('--token',      required=True,  help='Apify API token')
    parser.add_argument('--keywords',   default='',     help='Comma-separated filter keywords (for >1000 path)')
    parser.add_argument('--job-url',    default='',     help='Job URL — saved to _meta if provided')
    parser.add_argument('--output-dir', default='.',    help='Directory to write outputs (default: current dir)')
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    output_dir = args.output_dir

    # Step 1: Load CSV
    print(f'Loading {args.csv}...')
    rows = load_connections(args.csv)
    total = len(rows)
    print(f'  {total} connections found')

    # Step 2: Pre-filter if > 1000
    if total > 1000 and keywords:
        rows = filter_rows(rows, keywords)
        print(f'  After keyword filter: {len(rows)} connections (from {total})')
    elif total > 1000:
        print(f'  WARNING: {total} connections but no --keywords provided. Taking oldest 1000.')

    # Step 3: Sort by tenure (most tenured first), cap at 1000
    rows.sort(key=lambda r: r.get('_days_connected', 0), reverse=True)
    rows = rows[:1000]
    print(f'  Enriching {len(rows)} connections')

    # Step 4: Build inputs
    csv_lookup = {r.get('URL', '').strip().rstrip('/'): r for r in rows if r.get('URL', '').strip()}
    profile_urls = [r['URL'].strip() for r in rows if r.get('URL', '').strip()]
    print(f'  {len(profile_urls)} have profile URLs')

    # Step 5: Submit to Apify
    print(f'Submitting to Apify...')
    run_id = submit_apify_run(args.token, profile_urls)
    print(f'  Run ID: {run_id}')
    print('  Polling (this takes 5–30 minutes)...')

    # Step 6: Poll
    status, dataset_id = poll_apify_run(args.token, run_id)
    if status != 'SUCCEEDED':
        print(f'  Apify run ended with status: {status}. Continuing with partial results.')

    # Step 7: Download
    print('Downloading results...')
    raw = download_apify_results(args.token, dataset_id)
    print(f'  Downloaded {len(raw)} profiles (submitted {len(profile_urls)})')
    if len(raw) < len(profile_urls):
        print(f'  Note: {len(profile_urls) - len(raw)} profiles blocked by LinkedIn (normal)')

    # Step 8: Build output files
    profiles_dir = os.path.join(output_dir, 'profiles')
    os.makedirs(profiles_dir, exist_ok=True)

    new_entries = {}
    skipped = 0
    for profile in raw:
        url = get_url(profile)
        if not url:
            skipped += 1
            continue
        handle = handle_from_url(url)
        if not handle:
            skipped += 1
            continue

        csv_row = csv_lookup.get(url, {})

        # Write profile file
        profile_data = build_profile_file(profile)
        profile_path = os.path.join(profiles_dir, f'{handle}.json')
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)

        # Build index entry
        new_entries[url] = build_index_entry(profile, csv_row)

    if skipped:
        print(f'  Skipped {skipped} profiles (no URL or unrecognised handle)')

    # Step 9: Merge with existing index
    print('Merging with existing index...')
    index_path = os.path.join(output_dir, 'connections_index.json')
    merged = merge_index(new_entries, index_path)

    # Set _meta
    merged['_meta'] = {
        'jobUrl':       args.job_url,
        'created':      date.today().isoformat(),
        'totalInCsv':   total,
        'enrichedCount': len(new_entries),
        'filtered':     total > 1000,
    }

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f'\nDone.')
    print(f'  connections_index.json — {len(new_entries)} new/updated entries')
    print(f'  profiles/              — {len(new_entries)} files written')
    print(f'\n⚠️  Remember to revoke your Apify token at console.apify.com → Settings → API & Integrations')


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run tests**

```
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python -m pytest tests/test_enrich.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```
git add scripts/enrich_connections.py scripts/__init__.py tests/test_enrich.py
git commit -m "feat: add enrich_connections.py script with tests"
```

---

## Task 2: Create `tests/test_rank.py` and `scripts/rank_connections.py`

**Files:**
- Create: `tests/test_rank.py`
- Create: `scripts/rank_connections.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rank.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from rank_connections import (
    parse_tenure_years, mobility_bonus, relationship_bonus,
    passes_location_filter, passes_keyword_filter, slim_position,
)

# --- parse_tenure_years ---
def test_parse_tenure_years_years_months():
    assert abs(parse_tenure_years('3y 1m') - 3.083) < 0.01

def test_parse_tenure_years_years_only():
    assert parse_tenure_years('2y') == 2.0

def test_parse_tenure_years_months_only():
    assert abs(parse_tenure_years('6 mos') - 0.5) < 0.01

def test_parse_tenure_years_long_form():
    assert parse_tenure_years('2 yrs 4 mos') is not None

def test_parse_tenure_years_empty():
    assert parse_tenure_years('') is None

def test_parse_tenure_years_none():
    assert parse_tenure_years(None) is None

# --- mobility_bonus ---
def test_mobility_bonus_under_1_year():
    assert mobility_bonus('6 mos') == 0

def test_mobility_bonus_1_to_3_years():
    assert mobility_bonus('2y') == 5

def test_mobility_bonus_3_to_7_years():
    assert mobility_bonus('4y 2m') == 10

def test_mobility_bonus_over_7_years():
    assert mobility_bonus('8y') == 5

def test_mobility_bonus_unknown():
    assert mobility_bonus('') == 5   # neutral for unknown
    assert mobility_bonus(None) == 5

# --- relationship_bonus ---
def test_relationship_bonus_10_plus_years():
    assert relationship_bonus(365 * 11) == 10

def test_relationship_bonus_5_to_10_years():
    assert relationship_bonus(365 * 7) == 8

def test_relationship_bonus_3_to_5_years():
    assert relationship_bonus(365 * 4) == 5

def test_relationship_bonus_1_to_3_years():
    assert relationship_bonus(365 * 2) == 3

def test_relationship_bonus_under_1_year():
    assert relationship_bonus(180) == 1

# --- passes_location_filter ---
def test_location_filter_match():
    entry = {'location': 'Tel Aviv, Israel'}
    assert passes_location_filter(entry, 'Israel') is True

def test_location_filter_no_match():
    entry = {'location': 'New York, USA'}
    assert passes_location_filter(entry, 'Israel') is False

def test_location_filter_empty_location_keep():
    # Unknown location — always keep
    assert passes_location_filter({}, 'Israel') is True
    assert passes_location_filter({'location': ''}, 'Israel') is True

def test_location_filter_remote_keeps_all():
    entry = {'location': 'New York, USA'}
    assert passes_location_filter(entry, '') is True
    assert passes_location_filter(entry, 'remote') is True

# --- passes_keyword_filter ---
def test_keyword_filter_headline_match():
    entry = {'headline': 'Senior Software Engineer at Stripe', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, ['engineer', 'developer']) is True

def test_keyword_filter_no_match():
    entry = {'headline': 'Dentist', 'currentTitle': 'Dentist', 'currentCompany': 'Smile Clinic'}
    assert passes_keyword_filter(entry, ['engineer', 'developer', 'software']) is False

def test_keyword_filter_empty_fields_keep():
    # Unknown profession — always keep
    entry = {'headline': '', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, ['engineer']) is True

def test_keyword_filter_no_keywords_keeps_all():
    entry = {'headline': 'Dentist', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, []) is True

# --- slim_position ---
def test_slim_position_dict():
    p = {'title': 'Engineer', 'companyName': 'Acme', 'duration': '2y'}
    result = slim_position(p)
    assert 'Engineer' in result
    assert 'Acme' in result

def test_slim_position_string():
    assert slim_position('Backend Engineer at Stripe') == 'Backend Engineer at Stripe'

def test_slim_position_none():
    assert slim_position(None) is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python -m pytest tests/test_rank.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'rank_connections'`

- [ ] **Step 3: Write `scripts/rank_connections.py`**

Create `scripts/rank_connections.py`:

```python
#!/usr/bin/env python3
"""
LinkedIn connections ranking pipeline.

Two subcommands:

  prepare — filter index, load profiles, write batch files for Claude to score
    python scripts/rank_connections.py prepare \
        --keywords "engineer,backend,node,react" \
        --location "Israel"

  merge   — combine Claude's scores with index data, write ranked output
    python scripts/rank_connections.py merge \
        --scores _scores_tmp.json \
        --role-name "Senior Engineer @ Stripe" \
        --job-url "https://..."

Both commands default to connections_index.json and profiles/ in current directory.
"""
import argparse, json, os, re, shutil
from datetime import date


# ── Scoring helpers ───────────────────────────────────────────────────────────

def parse_tenure_years(s):
    """
    Parse Apify duration strings like '3y 1m', '2 yrs 4 mos', '6 mos' → float years.
    Returns None if string is empty or unrecognised.
    """
    if not s:
        return None
    s = s.lower()
    y = re.search(r'(\d+)\s*y', s)
    m = re.search(r'(\d+)\s*mo', s)
    years = (int(y.group(1)) if y else 0) + (int(m.group(1)) / 12 if m else 0)
    return years if (y or m) else None


def mobility_bonus(tenure_str):
    """
    Score 0–10 based on how long someone has been in their current role.
    Sweet spot is 3–7 years (prime window for a move).
    Unknown tenure → neutral score of 5.
    """
    yrs = parse_tenure_years(tenure_str)
    if yrs is None: return 5
    if yrs < 1:     return 0   # just started
    if yrs < 3:     return 5   # possible
    if yrs < 7:     return 10  # prime window
    return 5                   # settled, but not impossible


def relationship_bonus(days):
    """Score 1–10 based on days since LinkedIn connection."""
    years = days / 365
    if years >= 10: return 10
    if years >= 5:  return 8
    if years >= 3:  return 5
    if years >= 1:  return 3
    return 1


# ── Filters ───────────────────────────────────────────────────────────────────

def passes_location_filter(entry, location):
    """
    Returns True if the entry's location matches the required location string.
    Empty location (remote role) → always pass.
    Unknown entry location → always pass (keep, don't discard on missing data).
    """
    if not location or location.lower() == 'remote':
        return True
    loc = (entry.get('location') or '').lower()
    if not loc:
        return True  # unknown — keep
    return location.lower() in loc


def passes_keyword_filter(entry, keywords):
    """
    Returns True if any keyword appears in headline/title/company.
    Empty keywords list → always pass.
    Empty entry fields → always pass (keep unknowns).
    """
    if not keywords:
        return True
    text = ' '.join([
        entry.get('headline') or '',
        entry.get('currentTitle') or '',
        entry.get('currentCompany') or '',
    ]).lower().strip()
    if not text:
        return True  # unknown profession — keep
    return any(kw.lower() in text for kw in keywords)


# ── Profile slimming ──────────────────────────────────────────────────────────

def slim_position(p):
    """Convert Apify position dict or string to a readable string."""
    if not p:
        return None
    if isinstance(p, str):
        return p.strip() or None
    title   = p.get('title') or p.get('position') or ''
    company = p.get('companyName') or ''
    dur     = p.get('duration') or ''
    if title and company:
        base = f'{title} at {company}'
    else:
        base = title or company
    return (f'{base} ({dur})' if dur else base).strip() or None


def build_ranking_slim(url, index_entry, profile_data):
    """Build the minimal profile view sent to Claude for scoring."""
    positions = []
    for p in (profile_data.get('currentPosition') or [])[:1]:
        s = slim_position(p)
        if s: positions.append(s)
    for p in (profile_data.get('experience') or [])[:4]:
        s = slim_position(p)
        if s: positions.append(s)

    skills = list(dict.fromkeys(
        (profile_data.get('topSkills') or []) + (profile_data.get('skills') or [])
    ))[:10]

    return {
        'url':       url,
        'name':      f"{index_entry.get('firstName', '')} {index_entry.get('lastName', '')}".strip(),
        'headline':  index_entry.get('headline', ''),
        'positions': positions,
        'skills':    skills,
        'about':     (profile_data.get('about') or '')[:300],
    }


# ── Prepare subcommand ────────────────────────────────────────────────────────

def cmd_prepare(args):
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]

    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)
    entries = {k: v for k, v in index.items() if k != '_meta'}
    print(f'Loaded {len(entries)} entries from index')

    # Location filter
    loc_filtered = {
        url: e for url, e in entries.items()
        if passes_location_filter(e, args.location)
    }
    discarded_loc = len(entries) - len(loc_filtered)
    print(f'After location filter:  {len(loc_filtered)} kept, {discarded_loc} discarded (location="{args.location or "any"}")')

    # Keyword filter
    kw_filtered = {
        url: e for url, e in loc_filtered.items()
        if passes_keyword_filter(e, keywords)
    }
    discarded_kw = len(loc_filtered) - len(kw_filtered)
    print(f'After keyword filter:   {len(kw_filtered)} kept, {discarded_kw} discarded')

    # Load profile files
    profiles_dir = args.profiles_dir
    slims = []
    missing = 0
    for url, entry in kw_filtered.items():
        m = re.search(r'linkedin\.com/in/([^/?#]+)', url)
        if not m:
            missing += 1
            continue
        handle = m.group(1).rstrip('/')
        profile_path = os.path.join(profiles_dir, f'{handle}.json')
        if not os.path.exists(profile_path):
            missing += 1
            continue
        with open(profile_path, encoding='utf-8') as f:
            profile_data = json.load(f)
        slims.append(build_ranking_slim(url, entry, profile_data))

    if missing:
        print(f'Note: {missing} profiles not found in {profiles_dir}/ (skipped)')

    # Write batch files
    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    os.makedirs(batch_dir, exist_ok=True)
    batch_size = 25
    batches = [slims[i:i + batch_size] for i in range(0, len(slims), batch_size)]
    for idx, batch in enumerate(batches, 1):
        path = os.path.join(batch_dir, f'batch_{idx:02d}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)

    print(f'\nCreated {len(batches)} batch files in _rank_batches/')
    print(f'Total candidates to score: {len(slims)}')
    print(f'\nNext: score each _rank_batches/batch_NN.json, then run:')
    print(f'  python scripts/rank_connections.py merge --scores _scores_tmp.json --role-name "..."')


# ── Merge subcommand ──────────────────────────────────────────────────────────

def cmd_merge(args):
    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)

    with open(args.scores, encoding='utf-8') as f:
        all_scores = json.load(f)

    print(f'Merging {len(all_scores)} scores...')

    rankings = []
    for s in all_scores:
        url   = (s.get('url') or '').rstrip('/')
        entry = index.get(url, {})

        req = s.get('requirements_match', 0)
        sen = s.get('seniority_fit', 0)
        dom = s.get('domain_fit', 0)
        llm = round((req + sen + dom) / 3, 1)
        rel = relationship_bonus(entry.get('daysConnected', 0))
        mob = mobility_bonus(entry.get('tenureInRole', ''))
        final = round(llm * 0.80 + rel * 0.10 + mob * 0.10, 1)

        rankings.append({
            'url':                url,
            'final_score':        final,
            'llm_score':          llm,
            'requirements_match': req,
            'seniority_fit':      sen,
            'domain_fit':         dom,
            'relationship_bonus': rel,
            'mobility_bonus':     mob,
            'reason':             s.get('reason', ''),
        })

    rankings.sort(key=lambda x: x['final_score'], reverse=True)

    slug  = re.sub(r'[^a-z0-9]', '', args.role_name.lower())[:20] or 'role'
    today = date.today().strftime('%Y%m%d')
    filename = f'ranked_{slug}_{today}.json'
    out_path = os.path.join(args.output_dir, filename)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            '_meta': {
                'roleName': args.role_name,
                'jobUrl':   args.job_url,
                'created':  date.today().isoformat(),
            },
            'rankings': rankings,
        }, f, indent=2, ensure_ascii=False)

    print(f'Saved {filename} ({len(rankings)} candidates)\n')
    print('Top 10:')
    for i, r in enumerate(rankings[:10], 1):
        entry = index.get(r['url'], {})
        name  = f"{entry.get('firstName', '')} {entry.get('lastName', '')}".strip() or r['url']
        print(f'  {i:2}. {name:<30}  {r["final_score"]:4.1f}  {r["reason"][:60]}')

    # Clean up temp files
    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    if os.path.exists(batch_dir):
        shutil.rmtree(batch_dir)
    if os.path.exists(args.scores):
        os.remove(args.scores)
    print(f'\nCleaned up _rank_batches/ and {args.scores}')


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='LinkedIn connections ranking pipeline.')
    sub    = parser.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('prepare', help='Filter candidates and create LLM scoring batches')
    p.add_argument('--index',        default='connections_index.json')
    p.add_argument('--profiles-dir', default='profiles')
    p.add_argument('--keywords',     default='', help='Comma-separated job keywords')
    p.add_argument('--location',     default='', help='Required location string (empty = remote/any)')
    p.add_argument('--output-dir',   default='.')

    m = sub.add_parser('merge', help='Merge LLM scores and write ranked output file')
    m.add_argument('--index',      default='connections_index.json')
    m.add_argument('--scores',     default='_scores_tmp.json')
    m.add_argument('--role-name',  required=True, help='Short label for the CRM tab')
    m.add_argument('--job-url',    default='')
    m.add_argument('--output-dir', default='.')

    args = parser.parse_args()
    if args.cmd == 'prepare':
        cmd_prepare(args)
    elif args.cmd == 'merge':
        cmd_merge(args)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests**

```
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python -m pytest tests/test_rank.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```
git add scripts/rank_connections.py tests/test_rank.py
git commit -m "feat: add rank_connections.py script with tests"
```

---

## Task 3: Update `crm_server.py`

**Files:**
- Modify: `crm_server.py` (full replacement of the file — new endpoints, removed old ones)

The current server is at `C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper\crm_server.py`.

Key changes vs current:
- `/index` GET+POST replaces `/annotations` GET+POST
- `/profiles/<handle>` GET added (validates handle = alphanumeric+hyphens only)
- `/manifest` now scans only `ranked_*.json` (not `enriched_*.json`)
- `/data/<filename>` still serves ranked files

- [ ] **Step 1: Read current `crm_server.py` to understand the existing structure**

Read: `crm_server.py`

- [ ] **Step 2: Write updated `crm_server.py`**

Replace the entire file content:

```python
#!/usr/bin/env python3
"""Connections CRM local server. Run: python crm_server.py"""
import http.server, json, os, re, threading, webbrowser

PORT      = 8765
BASE      = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE, 'connections_crm.html')
INDEX_FILE = os.path.join(BASE, 'connections_index.json')
PROFILES_DIR = os.path.join(BASE, 'profiles')

RANKED_RE  = re.compile(r'^ranked[\w\-\.]+\.json$')
HANDLE_RE  = re.compile(r'^[a-zA-Z0-9\-]+$')   # safe profile handle


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._file(HTML_FILE, 'text/html')

        elif self.path == '/index':
            data = {}
            try:
                with open(INDEX_FILE, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
            self._json(data)

        elif self.path == '/manifest':
            self._json(self._scan())

        elif self.path.startswith('/profiles/'):
            handle = self.path[len('/profiles/'):]
            # Security: allow only safe handles, no path traversal
            if not HANDLE_RE.match(handle) or '..' in handle:
                self.send_response(403); self.end_headers(); return
            self._file(os.path.join(PROFILES_DIR, f'{handle}.json'), 'application/json')

        elif self.path.startswith('/data/'):
            fn = self.path[6:]
            if not RANKED_RE.match(fn) or '..' in fn:
                self.send_response(403); self.end_headers(); return
            self._file(os.path.join(BASE, fn), 'application/json')

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == '/index':
            n    = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(n)
            try:
                data = json.loads(body)
                with open(INDEX_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._json({'ok': True})
            except Exception as e:
                self._json({'error': str(e)})
        else:
            self.send_response(404); self.end_headers()

    def _scan(self):
        roles = []
        try:
            for fn in sorted(os.listdir(BASE), reverse=True):
                if not RANKED_RE.match(fn):
                    continue
                fp = os.path.join(BASE, fn)
                cnt = 0
                role_name = None
                try:
                    with open(fp, encoding='utf-8') as f:
                        data = json.load(f)
                    # New format: { _meta: { roleName }, rankings: [...] }
                    if isinstance(data, dict) and '_meta' in data:
                        cnt = len(data.get('rankings', []))
                        role_name = data['_meta'].get('roleName')
                    # Legacy format: array with _role_name on each item
                    elif isinstance(data, list):
                        cnt = len(data)
                        if data and data[0].get('_role_name'):
                            role_name = data[0]['_role_name']
                except Exception:
                    pass
                date_part = re.sub(r'^ranked[\w]*_?', '', fn).replace('.json', '')
                label = role_name or ('Role · ' + date_part)
                roles.append({'filename': fn, 'label': label, 'count': cnt})
        except Exception:
            pass
        return {'roles': roles}

    def _file(self, path, ctype):
        try:
            with open(path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', ctype + '; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    srv = http.server.HTTPServer(('localhost', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f'Connections CRM running at {url}')
    print('Drop ranked_*.json files here — role tabs appear on refresh.')
    print('Press Ctrl+C to stop.')
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
```

- [ ] **Step 3: Verify server starts without error**

```
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python crm_server.py &
curl http://localhost:8765/manifest
```

Expected: `{"roles": [...]}` (may be empty array if no ranked files yet — that's fine)

Stop the server with Ctrl+C after verifying.

- [ ] **Step 4: Commit**

```
git add crm_server.py
git commit -m "feat: update crm_server.py with /index and /profiles endpoints"
```

---

## Task 4: Update `connections_crm.html`

**Files:**
- Modify: `connections_crm.html`

This is the largest change. The current HTML is at `connections_crm.html`.

Key JS changes:
1. **Boot**: fetch `/index` instead of `/manifest`+`/annotations`+enriched data files
2. **Tab model**: one always-present "All Connections" tab + role tabs from manifest
3. **Data loading**: All Connections from index entries; role tab merges ranked scores with index
4. **Row expand**: fetch `/profiles/{handle}` lazily; show loading state
5. **Score breakdown**: add Mobility component (6th score item)
6. **Annotation save**: POST to `/index` (full index object, not just annotations)

- [ ] **Step 1: Read the current `connections_crm.html` to understand its full structure**

Read: `connections_crm.html`

- [ ] **Step 2: Add CSS for profile loading state and 6-column score grid**

Find the existing `.score-breakdown` CSS rule. Add after it:

```css
.score-item { text-align: center; min-width: 48px; }
.profile-loading { color: #9ca3af; font-size: 13px; font-style: italic; padding: 8px 0; }
```

- [ ] **Step 3: Replace the entire `<script>` block**

The script tag starts with `<script>` and ends with `</script>` before `</body>`. Replace the entire contents with:

```javascript
var FAM_LABELS = { not_familiar: 'Not familiar', somewhat_familiar: 'Somewhat familiar', worked_together: 'Worked together', very_close: 'Very close' };
var REC_LABELS = { na: 'N/A', neutral: 'Neutral', would_work_with: 'Would work with', strongly_recommend: 'Strongly recommend' };
var FAM_SHORT  = { not_familiar: 'N/A', somewhat_familiar: 'Some', worked_together: 'Worked', very_close: 'Close' };
var REC_SHORT  = { na: 'N/A', would_not_recommend: 'No', neutral: 'Maybe', would_work_with: 'Yes', strongly_recommend: '★' };

// ── State ─────────────────────────────────────────────────────────────────────
var tabs = []; var activeIdx = -1; var index = {}; var saveTimer = null;
var famFilter = 'all'; var recFilter = 'all'; var activeSearch = ''; var currentPage = 1; var PAGE_SIZE = 50;
var expandedTr = null; var expandedDataRow = null; var expandedUrl = null;

// ── Boot ──────────────────────────────────────────────────────────────────────
Promise.all([
  fetch('/manifest').then(function(r){ return r.json(); }),
  fetch('/index').then(function(r){ return r.json(); }).catch(function(){ return {}; })
]).then(function(res) {
  var manifest = res[0]; index = res[1]; setStatus('','');

  // Always-present "All Connections" tab sourced from index
  var indexEntries = Object.keys(index).filter(function(k){ return k !== '_meta'; });
  tabs.push({ type: 'network', label: 'All Connections', count: indexEntries.length, data: null });

  // Role tabs from ranked files
  (manifest.roles || []).forEach(function(f) {
    tabs.push({ type: 'role', filename: f.filename, label: f.label, count: f.count, data: null, scoremap: {} });
  });

  if (tabs.length === 0) {
    document.getElementById('tbody').innerHTML = '<tr><td colspan="10"><div class="empty-state"><h2>No data</h2><p>Run get-enriched-connections to build connections_index.json</p></div></td></tr>';
    setStatus('No index file','error'); return;
  }
  buildTabs(); activateTab(0);
}).catch(function(){ setStatus('Server not responding','error'); });

// ── Tab rendering ─────────────────────────────────────────────────────────────
function buildTabs() {
  var el = document.getElementById('tabs'); el.innerHTML = ''; var lastType = null;
  tabs.forEach(function(tab, idx) {
    if (lastType === 'network' && tab.type === 'role') {
      var d = document.createElement('div'); d.className = 'tab-divider'; el.appendChild(d);
    }
    lastType = tab.type;
    var btn = document.createElement('button');
    btn.className = 'tab-btn' + (idx === activeIdx ? ' active' : '');
    btn.textContent = tab.label;
    if (tab.count) {
      var chip = document.createElement('span'); chip.className = 'tab-count'; chip.textContent = tab.count; btn.appendChild(chip);
    }
    btn.onclick = (function(i){ return function(){ activateTab(i); }; })(idx);
    el.appendChild(btn);
  });
}

function activateTab(idx) {
  activeIdx = idx; famFilter = 'all'; recFilter = 'all'; activeSearch = ''; currentPage = 1;
  document.getElementById('search').value = '';
  document.querySelectorAll('.ftag').forEach(function(b){ b.classList.toggle('sel', b.dataset.v === 'all'); });
  buildTabs();
  var tab = tabs[idx];
  if (tab.data) { updateHeader(tab.type); renderPage(); return; }
  if (tab.type === 'network') {
    // Load All Connections from index
    tab.data = Object.entries(index)
      .filter(function(kv){ return kv[0] !== '_meta'; })
      .map(function(kv){ return normalizeConn(kv[0], kv[1]); });
    updateHeader('network'); renderPage(); return;
  }
  // Role tab — load ranked file
  document.getElementById('tbody').innerHTML = '<tr class="loading-row"><td colspan="10">Loading ' + esc(tab.label) + '...</td></tr>';
  document.getElementById('pager').innerHTML = ''; setStatus('Loading...','saving');
  fetch('/data/' + tab.filename).then(function(r){ return r.json(); }).then(function(raw) {
    var rankings, meta;
    if (raw._meta && raw.rankings) {
      // New format
      rankings = raw.rankings; meta = raw._meta;
    } else if (Array.isArray(raw)) {
      // Legacy format (old ranked_connections_*.json arrays)
      rankings = raw.map(function(r){ return {
        url: r.url || r.linkedinUrl || '',
        final_score: r.final_score, llm_score: r.llm_score,
        requirements_match: r.requirements_match, seniority_fit: r.seniority_fit,
        domain_fit: r.domain_fit, relationship_bonus: r.relationship_bonus,
        mobility_bonus: r.mobility_bonus, reason: r.reason,
      }; });
      meta = { roleName: raw[0] && raw[0]._role_name };
    }
    if (meta && meta.roleName) { tab.label = meta.roleName; buildTabs(); }
    // Build scoremap
    tab.scoremap = {};
    rankings.forEach(function(r){ tab.scoremap[r.url] = r; });
    // Merge with index for display
    tab.data = rankings.map(function(r) {
      var entry = index[r.url] || {};
      var conn = normalizeConn(r.url, entry);
      conn.final_score = r.final_score; conn.llm_score = r.llm_score;
      conn.requirements_match = r.requirements_match; conn.seniority_fit = r.seniority_fit;
      conn.domain_fit = r.domain_fit; conn.relationship_bonus = r.relationship_bonus;
      conn.mobility_bonus = r.mobility_bonus; conn.reason = r.reason;
      return conn;
    });
    setStatus('',''); updateHeader('role'); renderPage();
  }).catch(function(){ setStatus('Failed to load ' + tab.filename,'error'); });
}

function normalizeConn(url, entry) {
  return {
    url: url,
    _name: ((entry.firstName || '') + ' ' + (entry.lastName || '')).trim() || url,
    firstName: entry.firstName || '', lastName: entry.lastName || '',
    headline: entry.headline || '',
    location: entry.location || '',
    currentTitle: entry.currentTitle || '',
    currentCompany: entry.currentCompany || '',
    tenureInRole: entry.tenureInRole || '',
    daysConnected: entry.daysConnected || 0,
  };
}

// ── Header ────────────────────────────────────────────────────────────────────
function updateHeader(type) {
  var t = document.getElementById('thead-row');
  if (type === 'role') {
    t.innerHTML = '<tr><th class="score-col">#</th><th>Name</th><th>Position</th><th class="score-col">Score</th><th class="score-col">Req.</th><th class="score-col">Senior.</th><th class="score-col">Domain</th><th>Familiarity</th><th>Recommendation</th><th></th></tr>';
  } else {
    t.innerHTML = '<tr><th>Name</th><th>Position</th><th>Location</th><th>Familiarity</th><th>Recommendation</th><th></th></tr>';
  }
}

// ── Annotation helpers ────────────────────────────────────────────────────────
function getAnn(url) {
  var e = index[url] || {};
  return {
    familiarity:    e.familiarity    || 'not_familiar',
    recommendation: e.recommendation || 'na',
    notes:          e.notes          || '',
    outreach:       e.outreach       || { reached_out: false, date: '', outcome: '' },
  };
}
function ensureEntry(url) {
  if (!index[url]) index[url] = {
    familiarity: 'not_familiar', recommendation: 'na', notes: '',
    outreach: { reached_out: false, date: '', outcome: '' }
  };
  return index[url];
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function esc(s){ return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function scoreCls(v){ return v >= 7 ? 'hi' : v >= 4 ? 'mid' : 'lo'; }
function setStatus(msg, cls){ var el = document.getElementById('save-status'); el.textContent = msg; el.className = 'save-status' + (cls ? ' '+cls : ''); }
function handleFromUrl(url){ var m = (url||'').match(/\/in\/([^/?#]+)/); return m ? m[1] : null; }

// ── Filtering & rendering ─────────────────────────────────────────────────────
function getFiltered() {
  var tab = tabs[activeIdx]; if (!tab || !tab.data) return [];
  var q = activeSearch.toLowerCase();
  return tab.data.filter(function(c) {
    var a = getAnn(c.url);
    if (famFilter !== 'all' && a.familiarity !== famFilter) return false;
    if (recFilter !== 'all' && a.recommendation !== recFilter) return false;
    if (!q) return true;
    var hay = (c._name + ' ' + (c.headline||'') + ' ' + (c.currentTitle||'') + ' ' + (c.currentCompany||'')).toLowerCase();
    return hay.indexOf(q) !== -1;
  });
}

function renderPage() {
  closeExpand();
  var tab = tabs[activeIdx]; var filtered = getFiltered(); var total = filtered.length;
  var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > pages) currentPage = 1;
  var slice = filtered.slice((currentPage-1)*PAGE_SIZE, currentPage*PAGE_SIZE);
  var type = tab ? tab.type : 'network';
  var tbody = document.getElementById('tbody'); tbody.innerHTML = '';
  if (total === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="no-results">No connections match.</td></tr>';
  } else {
    var frag = document.createDocumentFragment();
    slice.forEach(function(c, idx) {
      var url = c.url; var a = getAnn(url);
      var fam = a.familiarity || 'not_familiar'; var rec = a.recommendation || 'na';
      var tr = document.createElement('tr'); tr.className = 'data-row'; tr.dataset.url = url;
      var nameCell = url ? '<a class="name-link" href="'+esc(url)+'" target="_blank" onclick="event.stopPropagation()">'+esc(c._name)+'</a>' : esc(c._name);
      var pos1 = c.currentTitle && c.currentCompany ? c.currentTitle + ' at ' + c.currentCompany : (c.currentTitle || c.currentCompany || c.headline || '');
      var pos2 = c.tenureInRole || '';
      var posCell = (pos1 ? '<div class="pos-main">'+esc(pos1)+'</div>' : '') + (pos2 ? '<div class="pos-sub">'+esc(pos2)+'</div>' : '');
      var famCell = '<span class="fam-badge '+fam+'">'+FAM_LABELS[fam]+'</span>';
      var recCell = '<span class="rec-badge '+rec+'">'+REC_LABELS[rec]+'</span>';
      var cells = '';
      if (type === 'role') {
        var rank = (currentPage-1)*PAGE_SIZE+idx+1; var fs = c.final_score||0;
        var rm = c.requirements_match||0; var sf = c.seniority_fit||0; var df = c.domain_fit||0;
        cells = '<td class="td-rank">'+rank+'</td><td class="td-name">'+nameCell+'</td><td class="td-pos">'+posCell+'</td>'+
          '<td class="td-score"><span class="final-score">'+fs.toFixed(1)+'</span></td>'+
          '<td class="td-score"><span class="score-pill '+scoreCls(rm)+'">'+rm+'</span></td>'+
          '<td class="td-score"><span class="score-pill '+scoreCls(sf)+'">'+sf+'</span></td>'+
          '<td class="td-score"><span class="score-pill '+scoreCls(df)+'">'+df+'</span></td>'+
          '<td class="td-fam">'+famCell+'</td><td class="td-rec">'+recCell+'</td><td class="td-chev">&#8250;</td>';
      } else {
        cells = '<td class="td-name">'+nameCell+'</td><td class="td-pos">'+posCell+'</td>'+
          '<td class="td-loc">'+esc(c.location||'')+'</td>'+
          '<td class="td-fam">'+famCell+'</td><td class="td-rec">'+recCell+'</td><td class="td-chev">&#8250;</td>';
      }
      tr.innerHTML = cells;
      tr.addEventListener('click', (function(u, row, conn, t){ return function(){ toggleExpand(u, row, conn, t); }; })(url, tr, c, type));
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }
  var pg = document.getElementById('pager');
  var pages2 = Math.max(1, Math.ceil(total/PAGE_SIZE));
  pg.innerHTML = pages2 <= 1 ? '' : '<button class="pg-btn" onclick="goPage('+(currentPage-1)+')"'+(currentPage===1?' disabled':'')+'>&#8592; Prev</button><span class="pg-info">Page '+currentPage+' of '+pages2+' &nbsp;&middot;&nbsp; '+total+' shown</span><button class="pg-btn" onclick="goPage('+(currentPage+1)+')"'+(currentPage===pages2?' disabled':'')+'>Next &#8594;</button>';
  document.getElementById('vis-count').textContent = total + ' of ' + (tab && tab.data ? tab.data.length : 0);
  updateChips();
}

function goPage(n){ currentPage = n; renderPage(); window.scrollTo(0,0); }

function updateChips() {
  var tab = tabs[activeIdx]; var data = tab && tab.data ? tab.data : [];
  var famC = {}, recC = {};
  data.forEach(function(c){ var a = getAnn(c.url); famC[a.familiarity||'not_familiar'] = (famC[a.familiarity||'not_familiar']||0)+1; recC[a.recommendation||'na'] = (recC[a.recommendation||'na']||0)+1; });
  document.querySelectorAll('.ftag[data-dim="fam"][data-v]').forEach(function(btn){
    var v = btn.dataset.v, chip = btn.querySelector('.count-chip'); if (chip) chip.remove();
    if (v !== 'all' && famC[v]) { var ch = document.createElement('span'); ch.className = 'count-chip'; ch.textContent = famC[v]; btn.appendChild(ch); }
  });
  document.querySelectorAll('.ftag[data-dim="rec"][data-v]').forEach(function(btn){
    var v = btn.dataset.v, chip = btn.querySelector('.count-chip'); if (chip) chip.remove();
    if (v !== 'all' && recC[v]) { var ch = document.createElement('span'); ch.className = 'count-chip'; ch.textContent = recC[v]; btn.appendChild(ch); }
  });
}

// ── Expand panel ──────────────────────────────────────────────────────────────
function closeExpand() {
  if (expandedTr) { expandedTr.remove(); expandedTr = null; }
  if (expandedDataRow) { expandedDataRow.classList.remove('expanded'); var ch = expandedDataRow.querySelector('.td-chev'); if (ch) ch.textContent = '›'; expandedDataRow = null; }
  expandedUrl = null;
}

function toggleExpand(url, tr, c, type) {
  var wasOpen = (expandedUrl === url); closeExpand(); if (wasOpen) return;
  expandedUrl = url; expandedDataRow = tr; tr.classList.add('expanded');
  var chev = tr.querySelector('.td-chev'); if (chev) chev.textContent = '⌄';

  var a = getAnn(url); var fam = a.familiarity || 'not_familiar'; var rec = a.recommendation || 'na';
  var notFamiliar = (fam === 'not_familiar');
  var famPills = Object.keys(FAM_LABELS).map(function(v){ return '<button class="ann-pill'+(fam===v?' active':'')+'" data-dim="fam" data-v="'+v+'" onclick="pickAnn(this,event,\''+url+'\',\'fam\')">'+FAM_LABELS[v]+'</button>'; }).join('');
  var recPills = Object.keys(REC_LABELS).map(function(v){ var dis = (notFamiliar && v !== 'na') ? ' disabled' : ''; return '<button class="ann-pill'+(rec===v?' active':'')+dis+'" data-dim="rec" data-v="'+v+'" onclick="pickAnn(this,event,\''+url+'\',\'rec\')">'+REC_LABELS[v]+'</button>'; }).join('');

  var scoreSection = '';
  if (type === 'role' && c.final_score != null) {
    scoreSection = '<div class="lbl">Score breakdown</div><div class="score-breakdown">'+
      '<div class="score-item"><div class="si-val">'+(c.final_score||0).toFixed(1)+'</div><div class="si-lbl">Final</div></div>'+
      '<div class="score-item"><div class="si-val">'+(c.requirements_match||0)+'</div><div class="si-lbl">Req.</div></div>'+
      '<div class="score-item"><div class="si-val">'+(c.seniority_fit||0)+'</div><div class="si-lbl">Seniority</div></div>'+
      '<div class="score-item"><div class="si-val">'+(c.domain_fit||0)+'</div><div class="si-lbl">Domain</div></div>'+
      '<div class="score-item"><div class="si-val">'+(c.relationship_bonus||0)+'</div><div class="si-lbl">Tenure</div></div>'+
      '<div class="score-item"><div class="si-val">'+(c.mobility_bonus||0)+'</div><div class="si-lbl">Mobility</div></div>'+
      '</div>'+(c.reason ? '<div class="reason-text">'+esc(c.reason)+'</div>' : '');
  }

  var colSpan = (type === 'role') ? '10' : '6'; var outreach = a.outreach || {};
  var xtr = document.createElement('tr'); xtr.className = 'expand-row';
  xtr.innerHTML = '<td colspan="'+colSpan+'"><div class="expand-panel">'+
    '<div class="ep-col">'+
      '<div class="lbl">Familiarity</div><div class="pill-row" id="fp-'+esc(url)+'">'+famPills+'</div>'+
      '<div class="lbl">Recommendation</div><div class="pill-row" id="rp-'+esc(url)+'">'+recPills+'</div>'+
      '<div class="lbl">Notes</div><textarea class="notes-box" placeholder="Notes..." oninput="onField(this,\''+url+'\',\'notes\')">'+esc(a.notes||'')+'</textarea>'+
    '</div>'+
    '<div class="ep-col" id="profile-col-'+esc(url)+'">'+
      (scoreSection ? scoreSection+'<div style="margin-top:6px"></div>' : '')+
      '<div class="profile-loading">Loading profile...</div>'+
      '<div class="lbl">Outreach</div>'+
      '<div class="outreach-row"><label class="outreach-toggle"><input type="checkbox"'+(outreach.reached_out?' checked':'')+' onchange="onCheck(this,\''+url+'\')"> Reached out</label>'+
      '<input type="date" class="date-input" value="'+esc(outreach.date||'')+'" onchange="onDate(this,\''+url+'\')"></div>'+
      '<textarea class="outcome-box" placeholder="Outcome..." oninput="onField(this,\''+url+'\',\'outcome\')">'+esc(outreach.outcome||'')+'</textarea>'+
    '</div></div></td>';
  expandedTr = xtr; tr.insertAdjacentElement('afterend', xtr);

  // Lazy-load profile data
  var handle = handleFromUrl(url);
  if (handle) {
    fetch('/profiles/' + handle).then(function(r){ return r.json(); }).then(function(profile) {
      renderProfileInPanel(url, profile);
    }).catch(function() {
      var col = document.getElementById('profile-col-' + url);
      if (col) { var pl = col.querySelector('.profile-loading'); if (pl) pl.textContent = 'Profile not available.'; }
    });
  }
}

function renderProfileInPanel(url, profile) {
  var col = document.getElementById('profile-col-' + url);
  if (!col) return;
  var pl = col.querySelector('.profile-loading');
  if (!pl) return;

  // Build positions list
  var allPos = [];
  (profile.currentPosition || []).forEach(function(p) { var s = slimPos(p); if (s) allPos.push(s); });
  (profile.experience || []).forEach(function(p) { var s = slimPos(p); if (s) allPos.push(s); });

  var html = '';
  if (allPos.length > 0) {
    html += '<div class="lbl">Experience</div><div class="all-pos">'+allPos.map(esc).join('<br>')+'</div>';
  }
  if (profile.about) {
    html += '<div class="lbl" style="margin-top:8px">About</div><div class="reason-text">'+esc(profile.about)+'</div>';
  }
  if (html) {
    pl.outerHTML = html;
  } else {
    pl.textContent = '';
  }
}

function slimPos(p) {
  if (!p) return null;
  if (typeof p === 'string') return p.trim() || null;
  var title = p.title || p.position || '', company = p.companyName || '', dur = p.duration || '';
  var base = (title && company) ? title+' at '+company : (title || company);
  return (dur ? base+' ('+dur+')' : base).trim() || null;
}

// ── Annotation handlers ───────────────────────────────────────────────────────
function pickAnn(btn, e, url, dim) {
  e.stopPropagation(); var v = btn.dataset.v; var entry = ensureEntry(url);
  if (dim === 'fam') {
    entry.familiarity = v;
    if (v === 'not_familiar') {
      entry.recommendation = 'na';
      var rpr = document.getElementById('rp-'+url);
      if (rpr) rpr.querySelectorAll('.ann-pill').forEach(function(p){ p.classList.toggle('active', p.dataset.v==='na'); p.classList.toggle('disabled', p.dataset.v!=='na'); });
      if (expandedDataRow) { var rb = expandedDataRow.querySelector('.rec-badge'); if (rb) { rb.className='rec-badge na'; rb.textContent=REC_LABELS['na']; } }
    } else {
      var rpr2 = document.getElementById('rp-'+url);
      if (rpr2) rpr2.querySelectorAll('.ann-pill').forEach(function(p){ p.classList.remove('disabled'); });
    }
    if (expandedDataRow) { var fb = expandedDataRow.querySelector('.fam-badge'); if (fb) { fb.className='fam-badge '+v; fb.textContent=FAM_LABELS[v]; } }
  } else {
    entry.recommendation = v;
    if (expandedDataRow) { var rb2 = expandedDataRow.querySelector('.rec-badge'); if (rb2) { rb2.className='rec-badge '+v; rb2.textContent=REC_LABELS[v]; } }
  }
  btn.closest('.pill-row').querySelectorAll('.ann-pill[data-dim="'+dim+'"]').forEach(function(p){ p.classList.toggle('active', p.dataset.v===v); });
  scheduleSave(); updateChips();
}

function onField(el, url, field) {
  var entry = ensureEntry(url);
  if (field === 'notes') { entry.notes = el.value; }
  if (field === 'outcome') { if (!entry.outreach) entry.outreach={}; entry.outreach.outcome = el.value; }
  scheduleSave();
}
function onCheck(el, url) { var entry = ensureEntry(url); if (!entry.outreach) entry.outreach={}; entry.outreach.reached_out = el.checked; scheduleSave(); }
function onDate(el, url)  { var entry = ensureEntry(url); if (!entry.outreach) entry.outreach={}; entry.outreach.date = el.value; scheduleSave(); }

function setFilter(dim, v) {
  if (dim === 'fam') famFilter = v; else recFilter = v; currentPage = 1;
  document.querySelectorAll('.ftag[data-dim="'+dim+'"]').forEach(function(b){ b.classList.toggle('sel', b.dataset.v===v); }); renderPage();
}

document.getElementById('search').addEventListener('input', function(e){ activeSearch = e.target.value; currentPage = 1; renderPage(); });

function scheduleSave(){ setStatus('Saving...','saving'); clearTimeout(saveTimer); saveTimer = setTimeout(doSave, 600); }
function doSave() {
  fetch('/index', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(index) })
    .then(function(){ setStatus('Saved ✓','saved'); })
    .catch(function(){ setStatus('Save failed','error'); });
}
```

- [ ] **Step 4: Verify the CRM loads**

Start the server and open the browser:
```
python crm_server.py
```

Open http://localhost:8765. Expected:
- "All Connections" tab appears (may show 0 if no index file yet — that's fine)
- No JS console errors
- Annotation changes auto-save

Stop server with Ctrl+C.

- [ ] **Step 5: Commit**

```
git add connections_crm.html
git commit -m "feat: update CRM HTML to load from index, lazy-load profiles, add mobility score"
```

---

## Task 5: Update `get-enriched-connections` skill

**Files:**
- Modify: `C:\Users\Taranis\.claude\skills\get-enriched-connections\SKILL.md`

- [ ] **Step 1: Write the new skill**

Replace the entire contents of `C:\Users\Taranis\.claude\skills\get-enriched-connections\SKILL.md`:

```markdown
---
name: get-enriched-connections
description: Use when the user wants to enrich their LinkedIn connections with full profile data. Triggers on: "enrich my connections", "get profile data for my connections", "download LinkedIn profiles", "prepare connections for ranking". Covers CSV export guide, Apify token setup, running the scraper, and producing connections_index.json + profiles/ folder.
---

# Get Enriched Connections

## Overview
Takes the user's LinkedIn Connections.csv, runs Apify enrichment, and produces two outputs:
- `connections_index.json` — lightweight URL-keyed map of all enriched connections (display fields + blank annotation fields). Replaces both the old enriched JSON and annotations files.
- `profiles/` folder — one JSON file per person with full profile data (loaded only when needed).

**Script:** `scripts/enrich_connections.py` in the project folder.

---

## Step 0 — Check prerequisites

### 0a. Connections.csv
Ask the user for the path to their Connections.csv. If they don't have it:

---
**How to export your LinkedIn connections:**
1. Go to linkedin.com → click your profile picture → **Settings & Privacy**
2. Left sidebar → **Data privacy** → **Download your data**
3. Select **"Download larger data archive, including connections…"** → **Request archive**
4. LinkedIn emails a link within 24 hours. Download the ZIP → extract → find **Connections.csv**

Only `Connections.csv` is needed from the ZIP.

---

### 0b. Apify token
Ask the user to paste their Apify API token. If they don't have one:

---
**How to get an Apify token (free tier is enough):**
1. Go to **console.apify.com** → Sign up
2. Click avatar → **Settings** → **API & Integrations**
3. Copy the token next to **Personal API tokens**
4. Paste it in chat — Claude will use it for this session only

**Cost:** ~$4 per 1000 profiles. Free tier gives $5/month.

**After the run:** Go back to Apify → API & Integrations → delete the token and create a fresh one next time.

---

Do not proceed until both are confirmed.

---

## Step 1 — Count connections and decide path

Read `scripts/enrich_connections.py` to understand the script, then run:

```python
import csv
with open(CSV_PATH, encoding='utf-8') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith('First Name'))
rows = list(csv.DictReader(lines[header_idx:]))
print(f'Total connections: {len(rows)}')
```

**If ≤ 1000:** Proceed to Step 2 with no keywords. Set `KEYWORDS = ""`.

**If > 1000:**
- Tell the user: *"You have N connections. To stay within Apify's free tier (~1000 profiles), I'll filter by job title keywords first. Please give me a job URL so I can extract the right keywords."*
- Ask for a job URL (can be the one they plan to rank for, or any relevant role)
- Use WebFetch to fetch the job posting
- Extract a broad list of title/skill keywords (e.g. for an engineering role: `engineer,developer,software,backend,frontend,fullstack,tech lead,cto,vp engineering,architect,data,devops,platform,product`)
- Set `KEYWORDS = "comma,separated,keywords"`
- Note: **err on the side of broad keywords** — it's better to enrich extra people than miss relevant ones

---

## Step 2 — Run the enrichment script

```bash
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python scripts/enrich_connections.py \
    --csv "PATH_TO_CSV" \
    --token "APIFY_TOKEN" \
    --keywords "KEYWORDS" \
    --job-url "JOB_URL_IF_ANY" \
    --output-dir "."
```

This will:
1. Load and filter/sort the CSV
2. Submit URLs to Apify
3. Poll until complete (5–30 minutes — tell user to wait)
4. Download results
5. Write `connections_index.json` and `profiles/` files
6. Merge with any existing annotation data (annotations are never overwritten)

---

## Done

Tell the user:
- `connections_index.json` written — N entries
- `profiles/` folder written — N files
- **Remind them to revoke the Apify token** at console.apify.com → Settings → API & Integrations → Delete
- Next step: use the **rank-connections** skill with a job URL to rank these profiles

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `UnicodeDecodeError` on CSV | Script uses `encoding='utf-8'` — should be fine. If not, open the CSV in Notepad and save as UTF-8. |
| CSV rows 1–3 are LinkedIn notes | Script handles this — finds real header by scanning for `First Name` |
| >1000 connections but no keywords | Script falls back to taking oldest 1000. Always provide keywords for >1000 to get relevant people. |
| Apify returns fewer profiles than submitted | Normal — LinkedIn blocks some. Script notes the count and continues. |
| `connections_annotations.json` exists | Script auto-migrates it into the new index — no data lost. |
```

- [ ] **Step 2: Commit**

```
git add "C:\Users\Taranis\.claude\skills\get-enriched-connections\SKILL.md"
git commit -m "feat: rewrite get-enriched-connections skill to use script"
```

---

## Task 6: Update `rank-connections` skill

**Files:**
- Modify: `C:\Users\Taranis\.claude\skills\rank-connections\SKILL.md`

- [ ] **Step 1: Write the new skill**

Replace entire contents of `C:\Users\Taranis\.claude\skills\rank-connections\SKILL.md`:

```markdown
---
name: rank-connections
description: Use when ranking LinkedIn connections for a specific job opening. Triggers on: "rank my connections for this job", "who should I refer", "find best matches in my network", "rank connections". Requires connections_index.json and profiles/ folder (from get-enriched-connections skill).
---

# Rank Connections

## Overview
Filters connections from `connections_index.json` by location and job keywords, loads profile files for relevant candidates, scores them inline, and writes `ranked_{slug}_{date}.json` — a slim file with scores and reasons that the CRM auto-discovers as a new role tab.

**Script:** `scripts/rank_connections.py` in the project folder.

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
cd "C:\Users\Taranis\Documents\Projects\LeadJobs Dev\LinkedIn connections scraper"
python scripts/rank_connections.py prepare \
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
python scripts/rank_connections.py merge \
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
```

- [ ] **Step 2: Commit**

```
git add "C:\Users\Taranis\.claude\skills\rank-connections\SKILL.md"
git commit -m "feat: rewrite rank-connections skill to use script"
```

---

## Task 7: Update `crm-connections` skill

**Files:**
- Modify: `C:\Users\Taranis\.claude\skills\crm-connections\SKILL.md`

- [ ] **Step 1: Read the current skill to understand the embedded templates**

Read: `C:\Users\Taranis\.claude\skills\crm-connections\SKILL.md`

- [ ] **Step 2: Update the skill overview and server script**

Replace the Overview section and the Server Script section with the new architecture description and updated `crm_server.py` content (identical to what was written in Task 3 Step 2).

Update the **Files** table:
```markdown
**Files:**
- `connections_crm.html` — static CRM UI (write once, never regenerate unless upgrading)
- `crm_server.py` — serves HTML + JSON files on localhost:8765
- `connections_index.json` — **GOLDEN DATA — NEVER DELETE OR OVERWRITE.** Combined display data + annotation store. Auto-created on first enrichment, updated by the CRM on every annotation change.
```

Update the **How the CRM works** table to reflect:
- Network tab sourced from `connections_index.json` (not enriched_*.json)
- Row expand fetches `profiles/{handle}.json` (lazy-loaded)
- Save writes to `/index` endpoint
- Manifest scans for `ranked_*.json` only

Update the **Server Script** section with the new `crm_server.py` from Task 3.

Update the **HTML Template** section with the updated `connections_crm.html` from Task 4.

- [ ] **Step 3: Commit**

```
git add "C:\Users\Taranis\.claude\skills\crm-connections\SKILL.md"
git commit -m "feat: update crm-connections skill with new architecture"
```

---

## Task 8: Deprecate `filter-connections` skill

**Files:**
- Modify: `C:\Users\Taranis\.claude\skills\filter-connections\SKILL.md`

- [ ] **Step 1: Replace skill content with deprecation notice**

Replace the entire contents of `C:\Users\Taranis\.claude\skills\filter-connections\SKILL.md`:

```markdown
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
```

Then append the original file content below the separator.

- [ ] **Step 2: Commit**

```
git add "C:\Users\Taranis\.claude\skills\filter-connections\SKILL.md"
git commit -m "chore: deprecate filter-connections skill"
```

---

## Self-Review Checklist

After all tasks are done, verify:

- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `python crm_server.py` starts without error
- [ ] `GET http://localhost:8765/manifest` returns `{"roles": [...]}`
- [ ] `GET http://localhost:8765/index` returns `{}` or existing index data
- [ ] CRM "All Connections" tab populates from index (if index exists)
- [ ] Role tab appears for any `ranked_*.json` file in folder
- [ ] Expanding a row triggers a profile fetch (check browser Network tab)
- [ ] Changing familiarity/recommendation auto-saves to `connections_index.json`
- [ ] `enrich_connections.py --help` prints usage without error
- [ ] `rank_connections.py prepare --help` prints usage without error
- [ ] `rank_connections.py merge --help` prints usage without error
