# StackHawk API Skill — Design Spec

**Date:** 2026-03-27
**Status:** Approved
**Author:** Scott Gerlach + Claude

---

## Overview

A Claude Code skill that guides agents through querying the StackHawk platform API
for security posture reporting and findings analysis. Separate from the hawkscan skill
which handles scanning and code remediation.

**Primary audience:** Security engineers doing reporting and triage.
**Core scenarios:** Org-wide posture summary (cross-app) and single-app deep dive.

---

## Separation from Hawkscan Skill

| Concern | hawkscan skill | stackhawk-api skill |
|---------|---------------|---------------------|
| Audience | Developers in a coding loop | Security engineers doing reporting |
| Triggers | "scan my app", "hawkscan", "stackhawk.yml" | "security posture", "show findings", "what needs attention" |
| Data source | CLI (`hawk scan`, `--json-output`) | StackHawk REST API (`api.stackhawk.com`) |
| Action | Run scans, generate fix tasks, remediate | Query, analyze, present, triage |

Two separate plugins in the same marketplace repo. Each installs independently.

---

## Skill Identity

**Name:** `stackhawk-api`

**Trigger words:** "stackhawk api", "security posture", "findings report", "show me
findings", "untriaged findings", "which apps", "scan history", "security dashboard",
"triage", "what needs attention", "app.stackhawk.com"

**Does NOT trigger for:** "scan my app", "hawkscan", "stackhawk.yml", "run a scan",
"DAST", "dynamic security testing" — those belong to the hawkscan skill.

---

## SKILL.md Workflow (5 Steps)

### Step 1: Assess Context

Before making API calls, determine:

1. **Does the agent have `HAWK_API_KEY`?** Required for all API calls. If missing,
   direct user to app.stackhawk.com -> Settings -> API Keys.
2. **Does the agent know the `orgId`?** If not, authenticate and discover it from
   the JWT claims or org list.
3. **What does the user want?** Route to the right workflow:
   - "What's my security posture?" -> Step 3 (Org Posture)
   - "Tell me about this app's findings" -> Step 4 (App Deep Dive)
   - "What hasn't been scanned recently?" -> Step 3 with stale-app filter

### Step 2: Authenticate

- Auth flow: `X-ApiKey` header to login endpoint -> JWT Bearer token (30 min expiry)
- Inline `curl` example for quick single calls
- Reusable helper script pattern for multi-call sessions (handles auth, token caching,
  401 re-auth, pagination)
- Teach the agent to detect 401 and re-authenticate

### Step 3: Org Posture Summary

- List environments (V2 endpoint — has untriaged counts baked in per env)
- Present summary: apps by severity counts, apps with no recent scans, apps with
  most untriaged High/Medium findings
- Agent formats as a table or structured summary
- If user wants to drill down on a specific app -> go to Step 4

### Step 4: App Deep Dive

- Hierarchical drill-down: List scan results -> List scan result alerts -> List scan
  result alert findings
- Present: what was found, severity, affected paths, triage status
- Link back to platform URL for each finding
- Compare scans when user asks "what changed?"

### Step 5: Present Results

- Guidance on formatting output (tables, summaries, actionable recommendations)
- When to suggest the user open the platform UI vs. when API data is sufficient
- How to suggest next actions (triage findings, re-scan, fix code via hawkscan skill)

---

## Reference Files

### `references/api-auth.md`

- Full auth flow documentation: API key -> JWT
- Inline `curl` example for the login endpoint
- Reusable shell helper script pattern:
  - Handles auth and token caching within a session
  - Detects 401 and re-authenticates automatically
  - Handles pagination (both V1 `pageToken` and V2 `page` styles)
  - Agent writes to a temp file, sources it for subsequent calls
- Environment variable: `HAWK_API_KEY` (same as hawkscan skill)

### `references/api-endpoints.md`

Endpoint catalog grouped by resource:

- **Auth:** Login, refresh token
- **Applications:** List (V2 paginated), get, create, update, delete
- **Environments:** List (V2 paginated with untriaged counts), create, update, delete
- **Scans:** List scan results for an app
- **Alerts:** List alerts for a scan
- **Findings:** List findings for an alert (the drill-down chain)
- **Teams:** List, get, create, update, delete, reassign apps
- **Audit:** Activity log for the org

For each endpoint: method, path, key params, abbreviated response shape (fields an
agent needs, not full schemas). Pagination patterns documented (V1 vs V2).

The scan -> alerts -> findings drill-down chain documented as an explicit sequence
with example calls.

### `references/reporting-recipes.md`

Pre-built compositions for common reporting questions:

- **"Org security posture"** — List envs, aggregate untriaged counts by severity,
  flag apps with most issues, flag stale apps (no scan in 30+ days)
- **"App deep dive"** — Get latest scan -> list alerts -> expand High/Medium findings
  with paths and triage status
- **"Stale apps"** — List envs filtered by lastScanDate, flag anything > 30 days
- **"What changed since last scan?"** — Compare two scan results for an app, show
  new/resolved findings

Each recipe: what endpoints to call, in what order, how to compose the results into
a useful presentation.

---

## Plugin Structure

```
plugins/
  hawkscan/                          # existing — unchanged
    .claude-plugin/plugin.json
    skills/hawkscan/
      SKILL.md
      references/
        cli-reference.md
        config-patterns.md
        docker-usage.md
        findings-and-fixes.md
        installation.md
    README.md
  stackhawk-api/                     # new
    .claude-plugin/plugin.json
    skills/stackhawk-api/
      SKILL.md
      references/
        api-auth.md
        api-endpoints.md
        reporting-recipes.md
    README.md
```

**marketplace.json** gets a second entry:

```json
{
  "name": "stackhawk-api",
  "description": "Query the StackHawk platform API for security posture reporting, findings analysis, and app management.",
  "category": "security",
  "source": "./plugins/stackhawk-api",
  "version": "1.0.0"
}
```

---

## What's Explicitly Out of Scope

- **Triage write operations** (accept risk, false positive) — read-only reporting for v1
- **Webhook configuration** — niche admin task
- **Organization/user management** — admin-only, not reporting
- **OpenAPI spec upload** — belongs in hawkscan workflow
- **Compliance/export formats** (CSV, SARIF) — future add-on if needed

---

## Open Questions to Resolve During Implementation

1. **Exact scan/alert/findings endpoint paths** — need to verify against actual API
   (not fully in public OpenAPI spec). Will reference falcon source or test against
   live API.
2. **Helper script language** — shell (bash) is simplest and most portable. Could
   offer a Python alternative for teams that prefer it. Start with bash only.
3. **Rate limiting** — need to check if the API has rate limits and document them if so.
