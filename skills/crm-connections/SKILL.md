---
name: crm-connections
description: 'Use when the user wants to open their networking CRM, annotate LinkedIn connections, or track outreach. Triggers on: "open my CRM", "open the ranked connections", "annotate my connections", "update my network", "track outreach".'
---

# CRM Connections

## Overview
A local HTML CRM served by a tiny Python server. The Network tab is sourced from `connections_index.json` (the combined display data + annotation store). Role tabs are built automatically from `ranked_*.json` files in the project folder. Expanding a row lazy-fetches full profile data from `profiles/{handle}.json`.

**Files (bundled in this skill — no setup needed):**
- `skills/crm-connections/scripts/crm_server.py` — server, run from project root
- `skills/crm-connections/assets/connections_crm.html` — CRM UI, served automatically
- `connections_index.json` — **GOLDEN DATA — NEVER DELETE OR OVERWRITE.** Combined display data + annotation store. Created by get-enriched-connections, updated on every annotation change.

---

## Run

```bash
python skills/crm-connections/scripts/crm_server.py
```

Opens http://localhost:8765 automatically. The Network tab loads from `connections_index.json` in the current directory. Role tabs appear for every `ranked_*.json` file in the same directory — no setup, just drop files and refresh.

---

## Done

Tell the user:
- CRM running at http://localhost:8765
- Network tab auto-loads from `connections_index.json`
- Role tabs auto-discovered from `ranked_*.json` files in the project folder
- Annotations auto-save to `connections_index.json` on every change
- Expanding a row lazy-loads full profile from `profiles/{handle}.json`

---

## How the CRM works

| Feature | How |
|---|---|
| **Tabs** | Network tab always present (from index). Role tabs auto-discovered from `ranked_*.json` files. |
| **Network tab** | Sourced from `connections_index.json` at boot. Columns: name, position, location, familiarity, recommendation |
| **Role tab** | Loads `ranked_*.json`, merges with index for display. Sorted by fit score. Columns: rank, name, position, score, req., seniority, domain, familiarity, recommendation |
| Expand a row | Click any row — shows familiarity pills, recommendation pills, score breakdown (role only), notes, outreach. Full profile (positions, about) lazy-fetched from `profiles/{handle}.json` |
| Filter | Two filter rows: familiarity + recommendation |
| Search | Live search across name, headline, position |
| Save | Automatic, 0.6s debounce, POSTs to `/index` endpoint, saves to `connections_index.json` |
| Tab label | Derived from filename date; override with `_meta.roleName` field in ranked JSON |
| Dark mode | Toggle via moon button in topbar |

---

## Annotation fields

**Familiarity** — how well do you know this person:
| Value | Label |
|---|---|
| `not_familiar` | Not familiar |
| `somewhat_familiar` | Somewhat familiar |
| `worked_together` | Worked together |
| `very_close` | Very close |

**Recommendation** — would you like to work with them again:
| Value | Label | Auto-set |
|---|---|---|
| `na` | N/A | Default when not_familiar |
| `neutral` | Neutral | — |
| `would_work_with` | Would work with | — |
| `strongly_recommend` | Strongly recommend | — |
| `would_not_recommend` | Would not recommend | — |
