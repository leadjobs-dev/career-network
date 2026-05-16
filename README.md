# career-network

A self-service system for maintaining your professional network — enrich LinkedIn connections, rank them for specific job openings, and track outreach through a local CRM.

Useful for both **finding a job** (who in your network can refer you?) and **referring others** (who is the best fit for an open role?).

---

## How it works

Three Claude skills form a pipeline:

| Step | Skill | What it does |
|------|-------|-------------|
| 1 | `get-enriched-connections` | Exports Connections.csv, enriches profiles via Apify, writes local database |
| 2 | `rank-connections` | Scores your network for a specific job using Claude's reasoning |
| 3 | `crm-connections` | Opens a local web CRM to annotate connections and track outreach |

All data stays on your machine — nothing is sent anywhere except to Apify for profile enrichment (which you can revoke after use).

---

## Prerequisites

- Python 3.9+
- [Claude Code](https://claude.ai/code)
- [Apify account](https://console.apify.com) — free tier (~$5/month credit) is enough

---

## Install

```bash
git clone https://github.com/leadjobs-dev/career-network.git
cd career-network
```

Then install the skills to Claude Code. On **macOS/Linux** use symlinks so edits in the repo are reflected immediately:

```bash
ln -s "$(pwd)/skills/crm-connections"          ~/.claude/skills/crm-connections
ln -s "$(pwd)/skills/get-enriched-connections" ~/.claude/skills/get-enriched-connections
ln -s "$(pwd)/skills/rank-connections"         ~/.claude/skills/rank-connections
```

On **Windows** (run in an admin PowerShell or with Developer Mode enabled):

```powershell
$repo = (Get-Location).Path
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\crm-connections"          -Target "$repo\skills\crm-connections"
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\get-enriched-connections" -Target "$repo\skills\get-enriched-connections"
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\rank-connections"         -Target "$repo\skills\rank-connections"
```

---

## Usage

Open a Claude Code session in the project directory and trigger each skill by describing what you want:

### Step 1 — Enrich your connections

> "Enrich my connections"

Claude triggers `get-enriched-connections`. It asks for your `Connections.csv` and Apify token, runs enrichment, and writes to `data/`.

**After the run:** revoke your Apify token at console.apify.com → Settings → API & Integrations.

### Step 2 — Rank for a job

> "Rank my connections for this job: [URL]"

Claude triggers `rank-connections`. It fetches the job description, filters your network by location and keywords, scores each candidate, and writes `data/ranked_*.json`.

### Step 3 — Open the CRM

> "Open my CRM"

Claude triggers `crm-connections`, which starts a local server at `http://localhost:8765`.

The **Network tab** shows all enriched connections. **Role tabs** appear automatically for every `ranked_*.json` file in `data/`. Click any row to expand it, annotate familiarity, leave notes, and track outreach.

---

## Data layout

```
career-network/
├── skills/                          # Claude skills (tracked in git)
│   ├── crm-connections/
│   ├── get-enriched-connections/
│   └── rank-connections/
├── tests/                           # Test suite
├── data/                            # YOUR LOCAL DATA — gitignored
│   ├── connections_index.json       #   enriched network + annotations
│   ├── profiles/                    #   full profile JSONs (lazy-loaded)
│   └── ranked_*.json                #   ranked results per job
└── README.md
```

The `data/` folder is gitignored. Your LinkedIn data, enriched profiles, and CRM annotations never leave your machine.

---

## Development

```bash
python -m pytest tests/ -v
```

---

## Contributing

PRs welcome for skill improvements, CRM UI enhancements, or new scoring logic. The `data/` folder is gitignored — don't commit personal data files.
