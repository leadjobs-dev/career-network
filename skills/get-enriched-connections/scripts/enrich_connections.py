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
import argparse, concurrent.futures, csv, json, os, re, time
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


def _duration_months(duration):
    """Parse common LinkedIn duration strings to months for comparison."""
    if not duration:
        return 0
    text = str(duration).lower()
    years = 0
    months = 0
    y = re.search(r'(\d+)\s*(?:y|yr|yrs|year|years)', text)
    m = re.search(r'(\d+)\s*(?:m|mo|mos|month|months)', text)
    if y:
        years = int(y.group(1))
    if m:
        months = int(m.group(1))
    return years * 12 + months


def _date_to_month_index(value, default_present=False):
    """Convert Apify date dicts like {'month': 'Oct', 'year': 2024} to a month index."""
    if not value:
        return None
    if isinstance(value, str):
        if default_present and value.lower() == 'present':
            today = date.today()
            return today.year * 12 + today.month
        return None
    text = (value.get('text') or '').lower()
    if default_present and text == 'present':
        today = date.today()
        return today.year * 12 + today.month
    year = value.get('year')
    if not year:
        return None
    months = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    }
    month = value.get('month')
    if isinstance(month, str):
        month = months.get(month[:3].lower(), 1)
    month = int(month or 1)
    return int(year) * 12 + month


def _format_duration_months(total_months):
    if total_months <= 0:
        return ''
    years, months = divmod(total_months, 12)
    parts = []
    if years:
        parts.append(f'{years} yr' + ('' if years == 1 else 's'))
    if months:
        parts.append(f'{months} mo' + ('' if months == 1 else 's'))
    return ' '.join(parts)


def get_tenure_in_role(profile):
    """
    Return tenure at the current company, not only in the current title.

    The field name is kept for compatibility with the CRM, but the intended
    meaning is current-company tenure so role tabs can estimate mobility.
    """
    pos = profile.get('currentPosition') or []
    if not pos:
        return ''
    current_company = (pos[0].get('companyName') or '').strip().lower()
    if not current_company:
        return pos[0].get('duration') or ''

    ranges = []
    fallback_durations = []
    seen_fallbacks = set()
    for p in list(pos) + list(profile.get('experience') or []):
        company = (p.get('companyName') or '').strip().lower()
        duration = p.get('duration') or ''
        if company != current_company:
            continue
        start = _date_to_month_index(p.get('startDate'))
        end = _date_to_month_index(p.get('endDate'), default_present=True)
        if start and end:
            ranges.append((start, end))
        elif duration:
            fallback_key = (
                (p.get('title') or p.get('position') or '').strip().lower(),
                company,
                duration,
            )
            if fallback_key in seen_fallbacks:
                continue
            seen_fallbacks.add(fallback_key)
            fallback_durations.append(duration)

    if ranges:
        start = min(r[0] for r in ranges)
        end = max(r[1] for r in ranges)
        return _format_duration_months(end - start) or pos[0].get('duration') or ''
    if not fallback_durations:
        return pos[0].get('duration') or ''
    return _format_duration_months(sum(_duration_months(d) for d in fallback_durations)) or pos[0].get('duration') or ''


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


def chunks(items, size):
    """Yield fixed-size chunks while preserving order."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _safe_batch_write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def run_apify_batch(token, batch_urls, batch_no, run_dir):
    """Run one Apify batch and persist raw results without touching the index."""
    batch_file = os.path.join(run_dir, f'batch_{batch_no:04d}.json')
    print(f'  Batch {batch_no:04d}: submitting {len(batch_urls)} profiles')
    run_id = submit_apify_run(token, batch_urls)
    _safe_batch_write(batch_file, {
        'batch': batch_no,
        'runId': run_id,
        'datasetId': None,
        'status': 'SUBMITTED',
        'profileUrls': batch_urls,
        'items': [],
    })

    status, dataset_id = poll_apify_run(token, run_id)
    raw = download_apify_results(token, dataset_id)
    _safe_batch_write(batch_file, {
        'batch': batch_no,
        'runId': run_id,
        'datasetId': dataset_id,
        'status': status,
        'profileUrls': batch_urls,
        'items': raw,
    })
    print(f'  Batch {batch_no:04d}: {status}, downloaded {len(raw)} profiles')
    return batch_file


def run_apify_batches(token, profile_urls, output_dir, batch_size, concurrency):
    """
    Run Apify in isolated batch files, then return combined raw items.

    Free Apify users can be capped at 10 items per run by some actors. Keeping
    each batch isolated also prevents concurrent writes to connections_index.json.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(output_dir, '_apify_runs', timestamp)
    os.makedirs(run_dir, exist_ok=True)
    batches = list(chunks(profile_urls, batch_size))
    concurrency = min(concurrency, 25)
    print(f'Running {len(batches)} Apify batch(es) of up to {batch_size} profiles')
    print(f'  Concurrency: {min(concurrency, len(batches))}')
    print(f'  Batch output: {run_dir}')

    save_run_state(run_dir)
    completed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(batches))) as executor:
        futures = {
            executor.submit(run_apify_batch, token, batch_urls, i + 1, run_dir): i + 1
            for i, batch_urls in enumerate(batches)
        }
        for future in concurrent.futures.as_completed(futures):
            batch_no = futures[future]
            try:
                completed.append(future.result())
            except Exception as e:
                print(f'  Batch {batch_no:04d}: ERROR: {e}')

    expected_files = [os.path.join(run_dir, f'batch_{i + 1:04d}.json') for i in range(len(batches))]
    missing = [p for p in expected_files if not os.path.exists(p)]
    if missing:
        raise RuntimeError(f'{len(missing)} Apify batch file(s) missing. Recover with --batch-dir "{run_dir}".')

    raw = []
    completed_urls = []
    failed = []
    for path in expected_files:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        completed_urls.extend(data.get('profileUrls') or [])
        if data.get('status') not in ('SUCCEEDED',):
            failed.append((path, data.get('status')))
        raw.extend(data.get('items') or [])

    if failed:
        details = ', '.join(f'{os.path.basename(path)}={status}' for path, status in failed)
        raise RuntimeError(f'Some Apify batches did not succeed: {details}. Recover with --batch-dir "{run_dir}" after fixing or rerunning failed batches.')
    return raw, completed_urls, run_dir


def load_apify_batches(batch_dir):
    raw = []
    profile_urls = []
    files = sorted(
        os.path.join(batch_dir, fn)
        for fn in os.listdir(batch_dir)
        if fn.startswith('batch_') and fn.endswith('.json')
    )
    if not files:
        raise ValueError(f'No batch_*.json files found in {batch_dir}')
    for path in files:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('status') != 'SUCCEEDED':
            raise RuntimeError(f'{path} has status {data.get("status")}; refusing to merge incomplete batch output')
        profile_urls.extend(data.get('profileUrls') or [])
        raw.extend(data.get('items') or [])
    return raw, profile_urls


# ── Main ──────────────────────────────────────────────────────────────────────

RECOVERY_FILE = '_apify_run.json'


def save_run_state(batch_dir):
    with open(RECOVERY_FILE, 'w', encoding='utf-8') as f:
        json.dump({'batch_dir': batch_dir}, f)


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
    parser.add_argument('--batch-dir',  default='',     help='Merge previously downloaded Apify batch files from this directory')
    parser.add_argument('--batch-size', type=int, default=10, help='Profiles per Apify run (default: 10)')
    parser.add_argument('--concurrency', type=int, default=25, help='Max concurrent Apify runs (default: 25)')
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    output_dir = args.output_dir
    index_path = os.path.join(output_dir, 'connections_index.json')
    if args.batch_size < 1:
        raise ValueError('--batch-size must be at least 1')
    if args.concurrency < 1:
        raise ValueError('--concurrency must be at least 1')

    # Check for leftover recovery file from a previous interrupted run
    if not args.batch_dir:
        state = load_run_state()
        if state:
            print(f'WARNING: Found {RECOVERY_FILE} from a previous run.')
            if state.get('batch_dir'):
                print(f'  To merge downloaded batch files, re-run with: --batch-dir "{state["batch_dir"]}"')
            else:
                print('  This recovery file is from an older unsupported single-run flow.')
                print('  Start a new batched run, or manually download old Apify data into a batch folder.')
            print(f'  Delete {RECOVERY_FILE} to suppress this warning.')
            print()

    if args.batch_dir:
        print(f'Recovery mode: merging Apify batch files from {args.batch_dir}')
        rows_all = load_connections(args.csv)
        csv_lookup = {r.get('URL', '').strip().rstrip('/'): r for r in rows_all if r.get('URL', '').strip()}
        raw, profile_urls = load_apify_batches(args.batch_dir)
        print(f'  Loaded {len(raw)} raw profiles from batch files ({len(profile_urls)} submitted URLs)')
        _merge_and_write(raw, csv_lookup, profile_urls, output_dir, index_path, args.job_url, len(rows_all))
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
            already = {u.rstrip('/').lower() for u in json.load(f) if not u.startswith('_')}
        before = len(rows)
        rows = [r for r in rows if r.get('URL', '').strip().rstrip('/').lower() not in already]
        skipped = before - len(rows)
        if skipped:
            print(f'  Already enriched: {skipped} skipped ({len(already)} total in index)')

    before_url_filter = len(rows)
    rows = [r for r in rows if r.get('URL', '').strip()]
    skipped_no_url = before_url_filter - len(rows)
    if skipped_no_url:
        print(f'  No profile URL: {skipped_no_url} skipped')

    # Apply limit
    if len(rows) > args.limit:
        print(f'  Applying limit: {args.limit} most-tenured profile URLs selected from {len(rows)} candidates')
        rows = rows[:args.limit]
    print(f'  Enriching {len(rows)} connections')

    # Step 4: Build inputs
    csv_lookup = {r.get('URL', '').strip().rstrip('/'): r for r in rows if r.get('URL', '').strip()}
    profile_urls = [r['URL'].strip() for r in rows if r.get('URL', '').strip()]
    print(f'  {len(profile_urls)} have profile URLs')

    if not profile_urls:
        print('No LinkedIn URLs found in CSV. Nothing to enrich.')
        return

    # Step 5: Submit to Apify in isolated batches and merge only after all finish.
    raw, submitted_urls, run_dir = run_apify_batches(
        args.token,
        profile_urls,
        output_dir,
        args.batch_size,
        args.concurrency,
    )
    print(f'Downloaded {len(raw)} raw profiles from {len(submitted_urls)} submitted URLs')
    if len(raw) < len(submitted_urls):
        print(
            f'  Note: {len(submitted_urls) - len(raw)} submitted URL(s) did not return data. '
            'Check the Apify run logs for actor limits, blocked/private profiles, or other scraper errors.'
        )
    print(f'  Raw batch files kept in {run_dir}')

    _merge_and_write(raw, csv_lookup, submitted_urls, output_dir, index_path, args.job_url, total)

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

    tmp_index_path = index_path + '.tmp'
    with open(tmp_index_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    os.replace(tmp_index_path, index_path)

    non_meta = sum(1 for k in merged if not k.startswith('_'))
    print(f'\nDone.')
    print(f'  New profiles added:    {len(new_entries)}')
    print(f'  Total in index now:    {non_meta}')
    print(f'  Profile files written: {len(new_entries)}')
    print(f'\nRemember to revoke your Apify token at console.apify.com -> Settings -> API & Integrations')


if __name__ == '__main__':
    main()
