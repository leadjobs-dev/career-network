---
name: ReferralFinder
description: 'Use to start the full ReferralFinder pipeline, find referrals for open company roles, or enrich LinkedIn connections. Triggers on: "find who to refer", "find someone to refer", "who in my network should I refer", "I want to refer someone to an open role", "enrich my connections", "get profile data for my connections", "prepare connections for ranking", "I have my Connections.csv", "I have my LinkedIn CSV", "I downloaded my connections", "here is my CSV", "I got the CSV".'
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

**If the user already has `Connections.csv`, skip the export instructions and go straight to Step 1.**

Otherwise, give the user these export instructions and wait:

---
**How to export your LinkedIn connections:**
1. Go to linkedin.com → click your profile picture → **Settings & Privacy**
2. Left sidebar → **Data privacy** → **Download your data**
3. Select **"Download larger data archive, including connections…"** → **Request archive**
4. LinkedIn sends a download link to your email — **this takes about 15–20 minutes**
5. Download the ZIP → extract → find **Connections.csv**

Only `Connections.csv` is needed from the ZIP.

---

End your message with this exact line so the user knows what to do next:

> "LinkedIn takes 15–20 minutes to send the download link. **When you have the file, reply with:** `I have my Connections.csv at [full path to file]`"

**When the user returns with the file path: do NOT analyze or comment on the CSV contents. Proceed immediately to Step 1.**

---

## Step 1 — Fetch job description and extract keywords

Use WebFetch on `JOB_URL`. Extract:
- Job title + synonyms
- Required skills / tech stack
- Seniority level
- Location (city/country, or remote)
- Company name

Set:
- `KEYWORDS` = broad comma-separated keywords covering the role domain (e.g. for marketing: `product marketing,marketing,marketer,gtm,brand,growth,content,demand generation,communications,pr,cmo`)
- `LOCATION` = city or country name, or `""` for remote

**Err on the side of broad keywords** — better to enrich extra people than miss relevant ones.

---

## Step 2 — Confirm scope with the user

If invoked from the rank-connections skill, the coverage check was already run and the user already chose how many to enrich — skip straight to Step 3.

If invoked directly, run the coverage check now:

```bash
python skills/rank-connections/scripts/rank_connections.py coverage \
    --csv "CSV_PATH" \
    --keywords "KEYWORDS"
```

Show the output to the user and let them pick an option. The command prints enriched vs. unenriched counts, cost tiers (500 / 1000 / 1250 / all), and a ready-to-run enrichment command.

**Do not ask for the Apify token until the user has confirmed how many profiles to enrich.**

---

## Step 3 — Get Apify token and run enrichment

Ask the user to paste their Apify token:

---
**What is Apify and why do we need it?**

LinkedIn doesn't let you download your connections' full profile data directly. Apify is a web scraping service that fetches that data for us — work history, skills, current role, location — everything we need to rank people intelligently.

**It costs $1 per 250 profiles** (~$4 per 1,000). Apify's free tier gives you $5/month of credit — enough for your first ~1,250 connections at no cost.

**Your token is used only for this session** — Claude runs the script locally on your machine. The token is never stored anywhere.

**How to get your Apify token (takes about 10 seconds):**
1. Go to **console.apify.com** and create a free account
2. Once logged in, click your avatar (top right) → **Settings**
3. Click **API & Integrations** in the left sidebar
4. Under **Personal API tokens**, click **+ Add new token**, give it any name, copy it
5. Paste it here in chat

**After the run is done:** Go back to that same page and delete the token. This is a good security habit — you'll create a fresh one next time.

---

Then run:

```bash
python skills/get-enriched-connections/scripts/enrich_connections.py \
    --csv "PATH_TO_CSV" \
    --token "APIFY_TOKEN" \
    --keywords "KEYWORDS" \
    --limit N \
    --job-url "JOB_URL_IF_ANY"
```

`--limit N` caps how many LinkedIn profile URLs are submitted to Apify (default: 1000). The script always picks the most-tenured (oldest connections first) up to that limit. Use the number the user chose from the coverage check. Rows with no LinkedIn URL are skipped before the limit is applied, so `--limit 40` means up to 40 actual profile URLs.

The script submits Apify in batches. This is the only supported enrichment path:
- `--batch-size 10` keeps each actor run within the free-user item limit seen on this actor.
- `--concurrency 25` uses Apify's concurrent-run capacity without running more than 25 actor runs at once.
- Each batch writes raw Apify output to `data/_apify_runs/<timestamp>/batch_XXXX.json`.
- `data/connections_index.json` is updated only once, after all batch files are downloaded and combined. Do not run several enrichment scripts in parallel against the same index.

The script will:
1. Load and filter the CSV by keywords
2. Skip any profiles already in `data/connections_index.json`
3. Skip rows with no LinkedIn URL, then apply `--limit`
4. Submit only new URLs to Apify in 10-profile batch runs, up to 25 runs concurrently
5. Save each batch's run ID, dataset ID, submitted URLs, and raw items into `data/_apify_runs/<timestamp>/`
6. Poll until complete — tell the user this can take **up to 2 hours for ~1,000 connections**, but they don't need to do anything; Claude will notify them when it's done
7. Combine all batch files, then merge once into `data/connections_index.json`
8. Write new per-profile files to `data/profiles/`
9. Delete `_apify_run.json` on success

If Apify returns fewer profiles than submitted, do **not** assume LinkedIn blocked the profiles. Check the Apify run logs. Common causes include actor free-user item limits, actor errors, private/blocked profiles, scraper output shape changes, or LinkedIn blocking.

**Tenure field semantics:** `tenureInRole` is kept as the CRM/index field name for compatibility, but it must represent tenure at the current company, not only the latest title at that company. When a profile has multiple current-company entries, use the longest duration for the current company so the CRM can estimate who may be more open to moving.

---

## Verify

After the script finishes, confirm the index actually grew:

```python
import json
with open('data/connections_index.json', encoding='utf-8') as f:
    idx = json.load(f)
print(sum(1 for k in idx if not k.startswith('_')), 'profiles in index')
```

The count should match the number of new profiles added. If it didn't grow, see Recovery below.

---

## Recovery (if script was interrupted after Apify submission)

If the script crashes or is killed during a batched Apify run, `_apify_run.json` will point at the batch folder. If the batch files exist, merge without re-submitting:

```bash
python skills/get-enriched-connections/scripts/enrich_connections.py \
    --csv "PATH_TO_CSV" \
    --token "APIFY_TOKEN" \
    --batch-dir "data/_apify_runs/YYYYMMDD_HHMMSS" \
    --job-url "JOB_URL_IF_ANY"
```

Do not use single-run dataset recovery. Batch files are the source of truth for enrichment recovery.

---

## Done

Tell the user:
- `data/connections_index.json` updated: N total entries (X new added)
- `data/profiles/`: N total files
- Raw Apify batch files are stored under `data/_apify_runs/<timestamp>/`
- **Remind them to revoke the Apify token** at console.apify.com -> Settings -> API & Integrations -> Delete

After the user confirms (or says they'll handle it), **automatically continue to rank their connections**: invoke the rank-connections skill and pass `JOB_URL` as the job URL for Step 0.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Asking for Apify token before showing the preview count | Always run Step 2 first: user should know the scope before committing |
| Proceeding to Apify before user has Connections.csv | **Always wait** for the user to confirm they have the file before moving to Step 1 |
| `UnicodeDecodeError` on CSV | Script uses `encoding='utf-8'`; if needed, open the CSV in Notepad and save as UTF-8 |
| Using `.encode('ascii', 'replace')` only on final print | Apply encoding handling per field, not on the whole formatted string |
| CSV rows 1-3 are LinkedIn notes | Script handles this by finding the real header with `First Name` |
| Not using `--limit` when user chose a specific count | The coverage command tells you the limit. Pass it explicitly with `--limit N`; default is 1000. The script applies the limit after skipping missing URLs |
| Apify free-user item limit exceeded | Use the built-in batch behavior: 10 profiles per run, up to 25 concurrent runs. Do not submit 40/500/1000 URLs in one actor run |
| Running multiple enrichment scripts in parallel | Do not do this. Let one script create isolated batch files and merge once at the end. Parallel scripts can corrupt or overwrite `connections_index.json` |
| Apify returns fewer profiles than submitted | Do not assume LinkedIn blocked them. Check Apify logs for actor limits, private/blocked profiles, actor errors, or output-shape changes |
| `connections_annotations.json` exists | Script auto-migrates it into the new index; no data lost |
| Index count didn't grow after script finished | Check whether Apify batch files contain usable URLs. If interrupted, re-run with `--batch-dir`. If all raw items lack URLs, inspect actor output/logs |
| `_apify_run.json` exists at start of new run | A previous run may not have been merged. Recover it first with `--batch-dir` before starting a new submission |
