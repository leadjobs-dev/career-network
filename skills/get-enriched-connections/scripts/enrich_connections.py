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
    header_idx = next(
        (i for i, l in enumerate(lines) if l.startswith('First Name')),
        None
    )
    if header_idx is None:
        raise ValueError(f"Could not find 'First Name' header in {csv_path}. Is this a LinkedIn Connections.csv?")
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


def _annotation_defaults():
    return {
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
        **_annotation_defaults(),
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
    else:
        annotations_path = os.path.join(os.path.dirname(os.path.abspath(index_path)), 'connections_annotations.json')
        if os.path.exists(annotations_path):
            # Migrate old-style annotations file
            with open(annotations_path, encoding='utf-8') as f:
                existing = json.load(f)
            print('Migrating connections_annotations.json -> connections_index.json')

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
    resp = requests.post(
        f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs',
        params={'token': token},
        json={
            'profileScraperMode': 'Profile details no email ($4 per 1k)',
            'queries': profile_urls,
        }
    )
    resp.raise_for_status()
    return resp.json()['data']['id']


def poll_apify_run(token, run_id):
    import requests
    while True:
        resp = requests.get(
            f'https://api.apify.com/v2/actor-runs/{run_id}',
            params={'token': token}
        )
        resp.raise_for_status()
        data = resp.json()['data']
        status = data['status']
        count = data['stats'].get('outputDatasetItems', '?')
        print(f'  Status: {status} | profiles done: {count}')
        if status in ('SUCCEEDED', 'FAILED', 'ABORTED'):
            return status, data['defaultDatasetId']
        time.sleep(15)


def download_apify_results(token, dataset_id):
    import requests
    resp = requests.get(
        f'https://api.apify.com/v2/datasets/{dataset_id}/items',
        params={'token': token, 'format': 'json'}
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ──────────────────────────────────────────────────────────────────────

RECOVERY_FILE = '_apify_run.json'


def save_run_state(run_id, dataset_id=None):
    with open(RECOVERY_FILE, 'w', encoding='utf-8') as f:
        json.dump({'run_id': run_id, 'dataset_id': dataset_id}, f)


def load_run_state():
    if os.path.exists(RECOVERY_FILE):
        with open(RECOVERY_FILE, encoding='utf-8') as f:
            return json.load(f)
    return None


def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description='Enrich LinkedIn connections via Apify.')
    parser.add_argument('--csv',        required=True,  help='Path to Connections.csv')
    parser.add_argument('--token',      required=True,  help='Apify API token')
    parser.add_argument('--keywords',   default='',     help='Comma-separated filter keywords')
    parser.add_argument('--limit',      type=int, default=1000, help='Max profiles to submit to Apify (default: 1000)')
    parser.add_argument('--job-url',    default='',     help='Job URL — saved to _meta if provided')
    parser.add_argument('--output-dir', default='data', help='Directory to write outputs (default: data/)')
    parser.add_argument('--dataset-id', default='',     help='Skip submission and download from this Apify dataset ID directly (recovery mode)')
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    output_dir = args.output_dir
    index_path = os.path.join(output_dir, 'connections_index.json')

    # Check for leftover recovery file from a previous interrupted run
    if not args.dataset_id:
        state = load_run_state()
        if state:
            print(f'WARNING: Found {RECOVERY_FILE} from a previous run (run_id={state["run_id"]}).')
            print(f'  This means a previous enrichment may not have been merged.')
            print(f'  To recover it, re-run with: --dataset-id {state.get("dataset_id") or "<check Apify console>"}')
            print(f'  Delete {RECOVERY_FILE} to suppress this warning.')
            print()

    # Recovery mode: skip straight to download
    if args.dataset_id:
        print(f'Recovery mode: downloading from dataset {args.dataset_id}')
        # Build csv_lookup from full CSV for _days_connected
        rows_all = load_connections(args.csv)
        csv_lookup = {r.get('URL', '').strip().rstrip('/'): r for r in rows_all if r.get('URL', '').strip()}
        raw = download_apify_results(args.token, args.dataset_id)
        print(f'  Downloaded {len(raw)} profiles')
        total = len(rows_all)
        profile_urls = []  # unknown in recovery mode
        _merge_and_write(raw, csv_lookup, profile_urls, output_dir, index_path, args.job_url, total)
        if os.path.exists(RECOVERY_FILE):
            os.remove(RECOVERY_FILE)
        return

    # Step 1: Load CSV
    print(f'Loading {args.csv}...')
    rows = load_connections(args.csv)
    total = len(rows)
    print(f'  {total} connections found')

    # Step 2: Keyword filter
    if keywords:
        rows = filter_rows(rows, keywords)
        print(f'  After keyword filter: {len(rows)} connections (from {total})')

    # Step 3: Sort by tenure (oldest connection = longest relationship, enriched first)
    rows.sort(key=lambda r: r.get('_days_connected', 0), reverse=True)

    # Step 3b: Skip profiles already in the index (incremental enrichment)
    if os.path.exists(index_path):
        with open(index_path, encoding='utf-8') as f:
            already = {u.rstrip('/').lower() for u in json.load(f)}
        before = len(rows)
        rows = [r for r in rows if r.get('URL', '').strip().rstrip('/').lower() not in already]
        skipped = before - len(rows)
        if skipped:
            print(f'  Already enriched: {skipped} skipped ({len(already)} total in index)')

    # Apply limit
    if len(rows) > args.limit:
        print(f'  Applying limit: {args.limit} most-tenured selected from {len(rows)} candidates')
        rows = rows[:args.limit]
    print(f'  Enriching {len(rows)} connections')

    # Step 4: Build inputs
    csv_lookup = {r.get('URL', '').strip().rstrip('/'): r for r in rows if r.get('URL', '').strip()}
    profile_urls = [r['URL'].strip() for r in rows if r.get('URL', '').strip()]
    print(f'  {len(profile_urls)} have profile URLs')

    if not profile_urls:
        print('No LinkedIn URLs found in CSV. Nothing to enrich.')
        return

    # Step 5: Submit to Apify — save run ID immediately so we can recover if interrupted
    print(f'Submitting to Apify...')
    run_id = submit_apify_run(args.token, profile_urls)
    save_run_state(run_id)
    print(f'  Run ID: {run_id}  (saved to {RECOVERY_FILE})')
    print('  Polling (this takes 5-30 minutes)...')

    # Step 6: Poll
    status, dataset_id = poll_apify_run(args.token, run_id)
    save_run_state(run_id, dataset_id)
    if status != 'SUCCEEDED':
        print(f'  Apify run ended with status: {status}. Continuing with partial results.')

    # Step 7: Download
    print('Downloading results...')
    raw = download_apify_results(args.token, dataset_id)
    print(f'  Downloaded {len(raw)} profiles (submitted {len(profile_urls)})')
    if len(raw) < len(profile_urls):
        print(f'  Note: {len(profile_urls) - len(raw)} profiles blocked by LinkedIn (normal)')

    _merge_and_write(raw, csv_lookup, profile_urls, output_dir, index_path, args.job_url, total)

    # Clean up recovery file on success
    if os.path.exists(RECOVERY_FILE):
        os.remove(RECOVERY_FILE)


def _merge_and_write(raw, csv_lookup, profile_urls, output_dir, index_path, job_url, total):
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

        profile_data = build_profile_file(profile)
        profile_path = os.path.join(profiles_dir, f'{handle}.json')
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)

        new_entries[url] = build_index_entry(profile, csv_row)

    if skipped:
        print(f'  Skipped {skipped} profiles (no URL or unrecognised handle)')

    print('Merging with existing index...')
    merged = merge_index(new_entries, index_path)

    merged['_meta'] = {
        'jobUrl':        job_url,
        'created':       date.today().isoformat(),
        'totalInCsv':    total,
        'enrichedCount': len(new_entries),
        'filtered':      total > 1000,
    }

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    non_meta = sum(1 for k in merged if not k.startswith('_'))
    print(f'\nDone.')
    print(f'  New profiles added:    {len(new_entries)}')
    print(f'  Total in index now:    {non_meta}')
    print(f'  Profile files written: {len(new_entries)}')
    print(f'\nRemember to revoke your Apify token at console.apify.com -> Settings -> API & Integrations')


if __name__ == '__main__':
    main()
