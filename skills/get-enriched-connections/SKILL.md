---
name: get-enriched-connections
description: 'Use to start the full referral-finding pipeline, or to enrich LinkedIn connections. Triggers on: "find who to refer", "find someone to refer", "who in my network should I refer", "I want to refer someone to an open role", "enrich my connections", "get profile data for my connections", "prepare connections for ranking".'
---

# Get Enriched Connections

## Overview
Takes the user's LinkedIn Connections.csv, runs Apify enrichment, and produces two outputs:
- `data/connections_index.json` — lightweight URL-keyed map of all enriched connections (display fields + blank annotation fields).
- `data/profiles/` folder — one JSON file per person with full profile data (loaded only when needed).

**Incremental:** If `data/connections_index.json` already exists, the script automatically skips profiles already in the index — only new profiles are sent to Apify. Annotations and familiarity ratings are always preserved.

**Script:** `skills/get-enriched-connections/scripts/enrich_connections.py` (run from your project root).

---

## Step 0 — Gather inputs

### 0a. Job URL

If the user provided a job URL in their message, capture it now. If not, ask:

> "What's the job URL? I'll use it to filter and rank your connections after enrichment."

Store as `JOB_URL`.

### 0b. Connections.csv

Give the user these export instructions, then **STOP AND WAIT** — do not proceed to Step 0c until the user explicitly confirms they have `Connections.csv` and provides the path to it:

---
**How to export your LinkedIn connections:**
1. Go to linkedin.com → click your profile picture → **Settings & Privacy**
2. Left sidebar → **Data privacy** → **Download your data**
3. Select **"Download larger data archive, including connections…"** → **Request archive**
4. LinkedIn sends a download link to your email — **this takes about 15–20 minutes**
5. Download the ZIP → extract → find **Connections.csv**

Only `Connections.csv` is needed from the ZIP.

---

**Wait here. Do not move on until the user confirms they have the file and tells you where it is.**

### 0c. Apify token

Explain what Apify is and ask the user to paste their token:

---
**What is Apify and why do we need it?**

LinkedIn doesn't let you download your connections' full profile data directly. Apify is a web scraping service that fetches that data for us — work history, skills, current role, location — everything we need to rank people intelligently.

**It costs ~$4 per 1,000 profiles.** Apify's free tier gives you $5/month of credit — enough for your first ~1,200 connections at no cost.

**Your token is used only for this session** — Claude runs the script locally on your machine. The token is never stored anywhere.

**How to get your Apify token (takes about 10 seconds):**
1. Go to **console.apify.com** and create a free account
2. Once logged in, click your avatar (top right) → **Settings**
3. Click **API & Integrations** in the left sidebar
4. Under **Personal API tokens**, click **+ Add new token**, give it any name, copy it
5. Paste it here in chat

**After the run is done:** Go back to that same page and delete the token. This is a good security habit — you'll create a fresh one next time.

---

---

## Step 1 — Count connections and decide path

Check how many connections are in the CSV and how many are already enriched:

```python
import csv, json, os
with open(CSV_PATH, encoding='utf-8') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith('First Name'))
rows = list(csv.DictReader(lines[header_idx:]))
total = len(rows)

already = 0
if os.path.exists('data/connections_index.json'):
    with open('data/connections_index.json', encoding='utf-8') as f:
        already = len(json.load(f))

print(f'Total connections: {total}')
print(f'Already enriched:  {already}')
print(f'New to enrich:     {total - already} (before keyword filter)')
```

**If already enriched ≥ total:** Nothing to do — all connections are in the index. Skip to Done.

**Decide on keywords:**

- **New to enrich ≤ 1000:** No keywords needed. Set `KEYWORDS = ""`.
- **New to enrich > 1000:** Need keywords to stay within Apify budget.
  - Tell the user: *"You have N new connections to enrich. To stay within Apify's free tier (~1000 profiles per run), I'll filter by job title keywords from the job posting."*
  - Use WebFetch on `JOB_URL` to extract a broad list of title/skill keywords (e.g. for an engineering role: `engineer,developer,software,backend,frontend,fullstack,tech lead,cto,vp engineering,architect,data,devops,platform,product`)
  - Set `KEYWORDS = "comma,separated,keywords"`
  - Note: **err on the side of broad keywords** — it's better to enrich extra people than miss relevant ones

---

## Step 2 — Run the enrichment script

```bash
python skills/get-enriched-connections/scripts/enrich_connections.py \
    --csv "PATH_TO_CSV" \
    --token "APIFY_TOKEN" \
    --keywords "KEYWORDS" \
    --job-url "JOB_URL_IF_ANY"
```

The script will:
1. Load and filter the CSV by keywords
2. Skip any profiles already in `data/connections_index.json`
3. Submit only new URLs to Apify
4. Poll until complete — tell the user this can take **up to 2 hours for ~1,000 connections**, but they don't need to do anything; Claude will notify them when it's done
5. Download results
6. Merge into `data/connections_index.json` (annotations never overwritten)
7. Write new per-profile files to `data/profiles/`

---

## Done

Tell the user:
- `data/connections_index.json` updated — N total entries (X new added)
- `data/profiles/` — N total files
- **Remind them to revoke the Apify token** at console.apify.com → Settings → API & Integrations → Delete

After the user confirms (or says they'll handle it), **automatically continue to rank their connections**: invoke the rank-connections skill and pass `JOB_URL` as the job URL for Step 0.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Proceeding to Apify before user has Connections.csv | **Always wait** for the user to confirm they have the file before moving to Step 0c |
| `UnicodeDecodeError` on CSV | Script uses `encoding='utf-8'` — should be fine. If not, open the CSV in Notepad and save as UTF-8. |
| CSV rows 1–3 are LinkedIn notes | Script handles this — finds real header by scanning for `First Name` |
| New to enrich > 1000 but no keywords | Script falls back to taking oldest 1000 new profiles. Always provide keywords for large networks. |
| Apify returns fewer profiles than submitted | Normal — LinkedIn blocks some. Script notes the count and continues. |
| `connections_annotations.json` exists | Script auto-migrates it into the new index — no data lost. |
