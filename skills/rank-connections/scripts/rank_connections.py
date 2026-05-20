#!/usr/bin/env python3
"""
LinkedIn connections ranking pipeline.

Subcommands:

  coverage         -- check how many keyword-matched connections are enriched vs. not
  prepare          -- filter index by location + headline keywords, build slim batch files
  write-prefilter  -- read batch files, write compact _prefilter.json for Claude to review
  apply-prefilter  -- rewrite batch files keeping only URLs from Claude's keep list
  merge            -- combine Claude's scores with index data, write ranked output file

Typical flow:
  0. python rank_connections.py coverage --csv data/Connections.csv --keywords "..."
  1. python rank_connections.py prepare --keywords "..." --location "..."
  2. python rank_connections.py write-prefilter
  3. Claude reads _prefilter.json, writes _prefilter_keep.json
  4. python rank_connections.py apply-prefilter --keep _prefilter_keep.json
  5. Claude scores each batch_NN.json  (writes _scores_batch_NN.json after each)
  6. python rank_connections.py merge --scores data/_scores_tmp.json --role-name "..."
"""
import argparse, csv as csv_mod, glob, json, os, re, shutil
from datetime import date, datetime


# -- Filters -------------------------------------------------------------------

def passes_location_filter(entry, location):
    if not location or location.lower() == 'remote':
        return True
    loc = (entry.get('location') or '').lower()
    if not loc:
        return True
    return location.lower() in loc


def passes_keyword_filter(entry, keywords):
    if not keywords:
        return True
    text = ' '.join([
        entry.get('headline') or '',
        entry.get('currentTitle') or '',
        entry.get('currentCompany') or '',
    ]).lower().strip()
    if not text:
        return True
    return any(kw.lower() in text for kw in keywords)


# -- Profile slimming ----------------------------------------------------------

def slim_position(p):
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
    """Full slim profile for scoring batches."""
    positions = []
    for p in (profile_data.get('currentPosition') or [])[:1]:
        s = slim_position(p)
        if s: positions.append(s)
    for p in (profile_data.get('experience') or [])[:4]:
        s = slim_position(p)
        if s: positions.append(s)

    def _as_str_list(val):
        if not val: return []
        if isinstance(val, str): return [s.strip() for s in val.split(',') if s.strip()]
        return [s['name'] if isinstance(s, dict) else str(s) for s in val]

    skills = list(dict.fromkeys(
        _as_str_list(profile_data.get('topSkills')) + _as_str_list(profile_data.get('skills'))
    ))[:10]

    return {
        'url':       url,
        'name':      f"{index_entry.get('firstName', '')} {index_entry.get('lastName', '')}".strip(),
        'headline':  index_entry.get('headline', ''),
        'positions': positions,
        'skills':    skills,
        'about':     (profile_data.get('about') or '')[:300],
    }


# -- Coverage subcommand -------------------------------------------------------

def cmd_coverage(args):
    """Report how many keyword-matched connections are enriched vs. not, with cost options."""
    with open(args.csv, encoding='utf-8-sig') as f:
        lines = f.readlines()
    header_idx = next((i for i, l in enumerate(lines) if 'First Name' in l), None)
    if header_idx is None:
        print('ERROR: Cannot find header row. Is this a LinkedIn Connections.csv?')
        return
    rows = list(csv_mod.DictReader(lines[header_idx:]))

    with open(args.index, encoding='utf-8') as f:
        idx = json.load(f)
    enriched_urls = {k.rstrip('/').lower() for k in idx if not k.startswith('_')}

    def get_url(r):
        return r.get('URL', '').strip().rstrip('/').lower()

    def parse_date(r):
        d = r.get('Connected On', '')
        for fmt in ('%d %b %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
            try:
                return datetime.strptime(d, fmt)
            except Exception:
                pass
        return None

    kws = [k.strip().lower() for k in args.keywords.split(',') if k.strip()]

    def matches(r):
        if not kws:
            return True
        text = (r.get('Position', '') + ' ' + r.get('Company', '')).lower()
        return any(k in text for k in kws)

    matched  = [r for r in rows if matches(r)]
    already  = [r for r in matched if get_url(r) in enriched_urls]
    need_raw = [r for r in matched if get_url(r) not in enriched_urls]
    need     = sorted(need_raw, key=lambda r: (parse_date(r) or datetime.max))

    def date_range(subset):
        dates = [d for d in (parse_date(r) for r in subset) if d]
        if not dates:
            return 'unknown dates'
        return f'{min(dates).strftime("%b %Y")} to {max(dates).strftime("%b %Y")}'

    print(f'CSV:              {len(rows):>6} total connections')
    print(f'Keyword-matched:  {len(matched):>6}')
    print(f'Already enriched: {len(already):>6}')
    print(f'Need enrichment:  {len(need):>6}')
    print()
    print('Options:')
    print(f'  a) Rank {len(already)} already-enriched  (free, instant - may miss people)')
    letter = ord('b')
    shown  = set()
    for lim in [500, 1000, 1250]:
        n = min(lim, len(need))
        if n == 0 or n in shown:
            continue
        shown.add(n)
        dr = date_range(need[:n])
        print(f'  {chr(letter)}) Enrich {n} most-tenured  ({dr})  ~${n / 250:.2f}')
        letter += 1
        if n < lim:
            break
    if len(need) not in shown and len(need) > 0:
        dr = date_range(need)
        print(f'  {chr(letter)}) Enrich all {len(need)}  ({dr})  ~${len(need) / 250:.2f}')
    print()
    if need and kws:
        kw_str = args.keywords
        print('To enrich N most-tenured, run (replace N and YOUR_TOKEN):')
        print(f'  python skills/get-enriched-connections/scripts/enrich_connections.py --csv {args.csv} --token YOUR_TOKEN --keywords "{kw_str}" --limit N')


# -- Prepare subcommand --------------------------------------------------------

def cmd_prepare(args):
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]

    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)
    entries = {k: v for k, v in index.items() if k != '_meta'}
    print(f'Loaded {len(entries)} entries from index')

    loc_filtered = {
        url: e for url, e in entries.items()
        if passes_location_filter(e, args.location)
    }
    print(f'After location filter:  {len(loc_filtered)} kept, {len(entries) - len(loc_filtered)} discarded (location="{args.location or "any"}")')

    kw_filtered = {
        url: e for url, e in loc_filtered.items()
        if passes_keyword_filter(e, keywords)
    }
    print(f'After keyword filter:   {len(kw_filtered)} kept, {len(loc_filtered) - len(kw_filtered)} discarded')

    profiles_dir = args.profiles_dir
    slims = []
    missing = 0
    for url, entry in kw_filtered.items():
        m = re.search(r'linkedin\.com/in/([^/?#]+)', url)
        if not m:
            missing += 1
            continue
        handle = m.group(1).rstrip('/')
        if not re.match(r'^[a-zA-Z0-9\-]+$', handle):
            missing += 1
            continue
        profile_path = os.path.join(profiles_dir, f'{handle}.json')
        if not os.path.exists(profile_path):
            missing += 1
            continue
        with open(profile_path, encoding='utf-8') as f:
            profile_data = json.load(f)
        slims.append(build_ranking_slim(url, entry, profile_data))

    if missing:
        print(f'Note: {missing} profiles not found in {profiles_dir}/ (skipped)')

    if not slims:
        print('WARNING: No candidates passed filters. Check --keywords and --location and try again.')
        return

    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    if os.path.isdir(batch_dir):
        shutil.rmtree(batch_dir)
    os.makedirs(batch_dir)
    batch_size = 25
    batches = [slims[i:i + batch_size] for i in range(0, len(slims), batch_size)]
    for idx, batch in enumerate(batches, 1):
        path = os.path.join(batch_dir, f'batch_{idx:02d}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)

    print(f'\nCreated {len(batches)} batch file(s) ({len(slims)} candidates) in _rank_batches/')
    print(f'\nNext: run write-prefilter, have Claude review _prefilter.json, then apply-prefilter.')


# -- Write-prefilter subcommand ------------------------------------------------

def _extract_title(position_str):
    """Extract just the job title from 'Title at Company (duration)'."""
    return re.sub(r'\s+at\s+.+', '', position_str).strip()


def cmd_write_prefilter(args):
    """Write compact _prefilter.json: headline + 2-sentence about + past role titles only."""
    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    if not os.path.isdir(batch_dir):
        print(f'ERROR: No batch directory at {batch_dir}. Run "prepare" first.')
        return

    batch_files = sorted(
        f for f in os.listdir(batch_dir)
        if f.startswith('batch_') and f.endswith('.json')
    )
    if not batch_files:
        print('No batch files found. Run "prepare" first.')
        return

    entries = []
    for fname in batch_files:
        with open(os.path.join(batch_dir, fname), encoding='utf-8') as f:
            batch = json.load(f)
        for p in batch:
            headline = (p.get('headline') or '').strip()

            # First 2 sentences of about (capped at 160 chars)
            about_raw = (p.get('about') or '').strip()
            sentences = re.split(r'(?<=[.!?])\s+', about_raw)
            about_snippet = ' '.join(sentences[:2])[:160].strip()

            # Role titles only — skip current (index 0), list the rest
            positions = p.get('positions') or []
            past_titles = [_extract_title(pos) for pos in positions[1:] if pos]

            parts = [headline]
            if about_snippet:
                parts.append(about_snippet)
            if past_titles:
                parts.append('Past: ' + ', '.join(past_titles))

            entries.append({
                'url':  p['url'],
                'name': p.get('name', ''),
                'line': ' | '.join(parts),
            })

    out_path = os.path.join(args.output_dir, '_prefilter.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f'Written {len(entries)} compact profiles to {out_path}')
    print(f'\nNext: read {out_path}, decide which URLs to keep, write _prefilter_keep.json,')
    print(f'then run: python rank_connections.py apply-prefilter --keep _prefilter_keep.json')


# -- Apply-prefilter subcommand ------------------------------------------------

def cmd_apply_prefilter(args):
    """Rewrite batch files keeping only URLs from the keep list."""
    with open(args.keep, encoding='utf-8') as f:
        keep_urls = {url.rstrip('/') for url in json.load(f)}
    print(f'Keep list: {len(keep_urls)} URLs')

    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    batch_files = sorted(
        f for f in os.listdir(batch_dir)
        if f.startswith('batch_') and f.endswith('.json')
    )

    all_profiles = []
    for fname in batch_files:
        with open(os.path.join(batch_dir, fname), encoding='utf-8') as f:
            all_profiles.extend(json.load(f))

    kept = [p for p in all_profiles if p['url'].rstrip('/') in keep_urls]
    print(f'Filtered: {len(all_profiles)} -> {len(kept)} kept, {len(all_profiles) - len(kept)} discarded')

    # Remove old batch files
    for fname in batch_files:
        os.remove(os.path.join(batch_dir, fname))

    if not kept:
        print('WARNING: No profiles kept. Check your keep list.')
        return

    batch_size = 25
    batches = [kept[i:i + batch_size] for i in range(0, len(kept), batch_size)]
    for idx, batch in enumerate(batches, 1):
        path = os.path.join(batch_dir, f'batch_{idx:02d}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)

    print(f'Rewritten to {len(batches)} batch file(s) in _rank_batches/')
    print(f'\nNext: score each _rank_batches/batch_NN.json, then run merge.')


# -- Merge subcommand ----------------------------------------------------------

def cmd_merge(args):
    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)

    with open(args.scores, encoding='utf-8') as f:
        all_scores = json.load(f)

    print(f'Merging {len(all_scores)} scores...')

    rankings = []
    for s in all_scores:
        url   = (s.get('url') or '').rstrip('/')
        score = float(s.get('score', 0) or 0)
        rankings.append({
            'url':     url,
            'score':   score,
            'reason':  s.get('reason', ''),
            'message': s.get('message', ''),
        })

    rankings.sort(key=lambda x: x['score'], reverse=True)

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
        print(f'  {i:2}. {name:<30}  {r["score"]:4.1f}  {r["reason"][:60]}')

    batch_dir = os.path.join(args.output_dir, '_rank_batches')
    if os.path.exists(batch_dir):
        shutil.rmtree(batch_dir)
    if os.path.exists(args.scores):
        os.remove(args.scores)
    for tmp in ['_prefilter.json', '_prefilter_keep.json']:
        p = os.path.join(args.output_dir, tmp)
        if os.path.exists(p):
            os.remove(p)
    for f in glob.glob(os.path.join(args.output_dir, '_scores_batch_*.json')):
        os.remove(f)
    print(f'Cleaned up temp files.')


# -- CLI -----------------------------------------------------------------------

def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description='LinkedIn connections ranking pipeline.')
    sub    = parser.add_subparsers(dest='cmd', required=True)
    _data  = 'data' if os.path.isdir('data') else '.'

    # coverage
    cv = sub.add_parser('coverage', help='Show enrichment coverage for a set of keywords')
    cv.add_argument('--csv',      required=True, help='Path to LinkedIn Connections.csv')
    cv.add_argument('--keywords', default='',    help='Comma-separated keywords to match against Position/Company')
    cv.add_argument('--index',    default=os.path.join(_data, 'connections_index.json'))

    # prepare
    p = sub.add_parser('prepare', help='Filter candidates and create batch files')
    p.add_argument('--index',        default=os.path.join(_data, 'connections_index.json'))
    p.add_argument('--profiles-dir', default=os.path.join(_data, 'profiles'))
    p.add_argument('--keywords',     default='', help='Comma-separated job keywords (headline/title filter)')
    p.add_argument('--location',     default='', help='Required location string (empty = remote/any)')
    p.add_argument('--output-dir',   default=_data)

    # write-prefilter
    wp = sub.add_parser('write-prefilter', help='Write compact _prefilter.json for Claude to review')
    wp.add_argument('--output-dir', default=_data)

    # apply-prefilter
    ap = sub.add_parser('apply-prefilter', help='Rewrite batch files keeping only URLs from keep list')
    ap.add_argument('--keep',       required=True, help='JSON file with list of URLs to keep')
    ap.add_argument('--output-dir', default=_data)

    # merge
    m = sub.add_parser('merge', help='Merge scores and write ranked output')
    m.add_argument('--index',      default=os.path.join(_data, 'connections_index.json'))
    m.add_argument('--scores',     default='_scores_tmp.json')
    m.add_argument('--role-name',  required=True)
    m.add_argument('--job-url',    default='')
    m.add_argument('--output-dir', default=_data)

    args = parser.parse_args()
    if   args.cmd == 'coverage':         cmd_coverage(args)
    elif args.cmd == 'prepare':          cmd_prepare(args)
    elif args.cmd == 'write-prefilter':  cmd_write_prefilter(args)
    elif args.cmd == 'apply-prefilter':  cmd_apply_prefilter(args)
    elif args.cmd == 'merge':            cmd_merge(args)


if __name__ == '__main__':
    main()
