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
    if not m:
        m = re.search(r'(\d+)\s*m\b', s)
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

        req = float(s.get('requirements_match', 0) or 0)
        sen = float(s.get('seniority_fit', 0) or 0)
        dom = float(s.get('domain_fit', 0) or 0)
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
