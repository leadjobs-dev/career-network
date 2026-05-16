# career-network

A private system for turning your LinkedIn connections into a ranked, searchable, annotated network — so you can answer "who should I reach out to about this job?" in minutes instead of hours.

**What you'll have at the end:** A local web app showing your connections ranked by fit for any job opening, with scores for requirements match, seniority, and domain. You can mark familiarity, leave notes, track outreach, and flag per-role fit — all saved privately on your machine.

Works for **finding a job** (who in your network can refer you?) and **referring others** (who is the best match for an open role?).

---

## How it works

Three skills form a pipeline — you trigger each one by describing what you want in Claude Code:

| Step | What you say | What happens |
|------|-------------|-------------|
| 1 | "Enrich my connections" | Claude walks you through exporting your LinkedIn data, enriches profiles via Apify, and builds a local database |
| 2 | "Rank my connections for this job: [URL]" | Claude scores every relevant person in your network for the role and saves the results |
| 3 | "Open my CRM" | A local web app opens at http://localhost:8765 showing your ranked connections |

All data stays on your machine. Nothing is stored in the cloud except temporarily during Apify enrichment (which you revoke after use).

---

## Prerequisites

- [Claude Code](https://claude.ai/code) — installed and working
- [Python 3.9+](https://www.python.org/downloads/) — for running local scripts
- [Apify account](https://console.apify.com) — free tier gives ~$5/month credit, enough for your first ~1,200 profiles

---

## Setup (one time)

**1. Create a fresh folder** anywhere on your computer — this is where your network data will live.

**2. Open Claude Code** in that folder. (In the Claude Code desktop app: File → Open Folder. In VS Code with the Claude Code extension: open the folder, then open Claude Code.)

**3. Install the skills** by running this in the Claude Code terminal (the `!` prefix runs shell commands):

```
! npx skills add leadjobs-dev/career-network
```

That's it. The `data/` folder will be created automatically when you run your first enrichment.

### Verify the install

After installing, type this to Claude:

> "What skills do you have for working with my LinkedIn connections?"

Claude should describe the three skills (enrich, rank, CRM). If it doesn't, try restarting Claude Code.

---

## Usage

Open Claude Code in your network folder and say:

### Step 1 — Enrich your connections

> "Enrich my connections"

Claude will ask for your `Connections.csv` (it explains how to export it from LinkedIn) and an Apify token (it explains how to get one for free). The enrichment runs in the background — 5–30 minutes depending on how many connections you have.

**Cost:** ~$4 per 1,000 profiles. Apify's free tier covers your first ~1,200 connections at no cost.

**After the run:** Claude will remind you to revoke your Apify token. Do this — it's a good security habit. You'll create a fresh one next time.

**Incremental:** Already ran this before? Just say "enrich my connections" again. Claude will only enrich new connections — existing profiles and all your notes are preserved.

### Step 2 — Rank for a job

> "Rank my connections for this job: [paste the job URL]"

Claude fetches the job description, filters your network by location and relevant keywords, scores every candidate on requirements match, seniority fit, and domain fit, and saves the results. It prints the top 10 when done.

### Step 3 — Open the CRM

> "Open my CRM"

Opens http://localhost:8765 automatically. You'll see:

- **Network tab** — all your enriched connections, searchable and filterable
- **Role tabs** — one per ranked job, sorted by fit score

Click any row to expand it: see the full score breakdown, leave notes, mark familiarity, rate whether you'd work with this person, and mark their fit for the specific role. Everything auto-saves.

---

## CRM features

| Feature | How it works |
|---------|-------------|
| **Sorting** | Click any column header — first click sorts highest first |
| **Filtering** | Filter rows at the top let you narrow by familiarity or recommendation |
| **Search** | Live search across name, position, company |
| **Role fit** | Per-role field (Strong / Good / Weak / Not a fit) — separate from your global recommendation |
| **Familiarity** | How well you know this person (Not familiar → Very close) |
| **Recommendation** | Would you work with them again? Saved globally, not per-role |
| **Notes** | Global notes + role-specific notes in the expand panel |
| **Outreach tracking** | Log whether you've reached out, when, and what happened |
| **Dark mode** | Toggle via the moon button |

---

## Your data

```
your-folder/
├── data/                        # YOUR DATA — stays on your machine
│   ├── connections_index.json   #   enriched profiles + all your annotations
│   ├── profiles/                #   full profile details (loaded on demand)
│   └── ranked_*.json            #   ranked results per job
```

Back up the `data/` folder occasionally — it contains everything. If you share this folder across machines, copy the whole `data/` folder.

---

## Updating the skills

To get the latest version of the skills:

```
! npx skills add leadjobs-dev/career-network
```

Run the same command — it updates in place.
