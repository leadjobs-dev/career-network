import json, os

RANKED_PATH      = None
ENRICHED_PATH    = 'enriched_profiles_20260502.json'
ANNOTATIONS_PATH = None

# ── Determine mode and load connections ────────────────────────────────────────
if RANKED_PATH:
    mode = 'role'
    with open(RANKED_PATH, encoding='utf-8') as f:
        connections = json.load(f)
    print(f'Role view: {len(connections)} ranked connections')
elif ENRICHED_PATH:
    mode = 'network'
    with open(ENRICHED_PATH, encoding='utf-8') as f:
        connections = json.load(f)
    print(f'Network view: {len(connections)} enriched connections')
else:
    raise ValueError('Provide either RANKED_PATH or ENRICHED_PATH')

# ── Normalize position objects -> plain strings ────────────────────────────────
def slim_pos(p):
    if not p: return None
    if isinstance(p, str): return p
    title   = p.get('title') or p.get('position') or ''
    company = p.get('companyName') or p.get('company') or ''
    dur     = p.get('duration') or ''
    parts = []
    if title and company: parts.append(title + ' at ' + company)
    elif title:           parts.append(title)
    elif company:         parts.append(company)
    if dur:               parts.append('(' + dur + ')')
    return ' '.join(parts).strip() or None

def slimlist(lst, limit=8):
    result = []
    for p in (lst or [])[:limit]:
        s = slim_pos(p)
        if s: result.append(s)
    return result

# ── Normalize each connection ──────────────────────────────────────────────────
for c in connections:
    url = c.get('url') or c.get('linkedinUrl') or ''
    if not url:
        oq = c.get('originalQuery')
        url = (oq.get('query') if isinstance(oq, dict) else oq) or ''
    c['url'] = url.rstrip('/')
    c['currentPosition'] = slimlist(c.get('currentPosition'), 3)
    c['experience']      = slimlist(c.get('experience'), 8)
    c['_days_connected'] = c.get('_days_connected') or c.get('days_connected') or 0

# ── Load annotations ───────────────────────────────────────────────────────────
annotations = {}
ann_path = ANNOTATIONS_PATH or 'connections_annotations.json'
if os.path.exists(ann_path):
    try:
        with open(ann_path, encoding='utf-8') as f:
            annotations = json.load(f)
        print(f'Loaded {len(annotations)} existing annotations')
    except Exception:
        print('Annotations file unreadable — starting fresh')

with open(ann_path, 'w', encoding='utf-8') as f:
    json.dump(annotations, f, indent=2, ensure_ascii=False)

# Embed-safe JSON
connections_json = json.dumps(connections, ensure_ascii=False).replace('</', '<\\/')
annotations_json = json.dumps(annotations, ensure_ascii=False).replace('</', '<\\/')

# ── Read HTML template from skill and inject data ──────────────────────────────
skill_path = r'C:\Users\Taranis\.claude\skills\crm-connections\SKILL.md'
with open(skill_path, encoding='utf-8') as f:
    skill = f.read()

MARKER = 'HTML = r"""<!DOCTYPE html>'
s = skill.rfind(MARKER) + len('HTML = r"""')  # rfind = last occurrence = actual template
e = skill.index('"""', s)
html = skill[s:e]
html = html.replace('__CONNECTIONS_JSON__', connections_json)
html = html.replace('__ANNOTATIONS_JSON__', annotations_json)
html = html.replace("'__MODE__'", f"'{mode}'")

with open('connections_crm.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Generated connections_crm.html ({mode} mode)')
print('Starts with:', open('connections_crm.html', encoding='utf-8').read(30))
