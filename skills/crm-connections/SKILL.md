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
| **Role tab** | Loads `ranked_*.json`, merges with index for display. Columns: rank, name, position, score, req., seniority, domain, role fit, familiarity, recommendation |
| **Sorting** | Click any column header to sort. First click = highest first for scores and categorical fields (fit, familiarity, recommendation); A→Z for name. Click again to reverse. |
| **Inline editing** | Familiarity, recommendation, and role fit can be set directly in the table row without expanding |
| **Expand a row** | Click any row — shows full annotation pills, score breakdown (role tabs), notes, role notes, outreach tracking. Profile (positions, about) lazy-fetched from `profiles/{handle}.json` |
| **Filter** | Two filter rows: familiarity + recommendation |
| **Search** | Live search across name, headline, position |
| **Save** | Automatic, 0.6s debounce, POSTs to `/index` endpoint, saves to `connections_index.json` |
| **Tab label** | Derived from `_meta.roleName` in ranked JSON, falls back to filename date |
| **Dark mode** | Toggle via moon button in topbar |

---

## Annotation fields

**Familiarity** — how well do you know this person (global, across all roles):
| Value | Label |
|---|---|
| `not_familiar` | Not familiar |
| `somewhat_familiar` | Somewhat familiar |
| `worked_together` | Worked together |
| `very_close` | Very close |

**Recommendation** — would you work with them again (global, across all roles):
| Value | Label |
|---|---|
| `na` | N/A (default when not familiar) |
| `neutral` | Neutral |
| `would_work_with` | Would work with |
| `strongly_recommend` | Strongly recommend |
| `would_not_recommend` | Would not recommend |

**Role fit** — is this person a fit for this specific role (per-role, stored under `index[url].roles[filename]`):
| Value | Label |
|---|---|
| `unset` | Not reviewed |
| `strong` | Strong fit |
| `good` | Good fit |
| `weak` | Weak fit |
| `not_a_fit` | Not a fit |
