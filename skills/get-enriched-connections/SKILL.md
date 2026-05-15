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
