---
name: api
version: 1.13.2
description: >
  Use this skill when a user or agent needs to query the StackHawk platform for
  security reporting, findings analysis, or app management. Triggers include:
  "stackhawk api", "security posture", "findings report", "show me findings",
  "untriaged findings", "which apps", "scan history", "security dashboard",
  "triage", "what needs attention". Prefers the `hawkop` CLI when installed;
  falls back to raw REST calls otherwise. Do NOT use for running scans (use the
  hawkscan skill for "scan my app", "hawkscan", "stackhawk.yml", "DAST") or for
  fixing/remediating code or vulnerabilities — this skill only reads and reports
  platform data.
---

# StackHawk API Skill

This skill enables Claude to act as a security reporting agent against the StackHawk
platform. The core workflow is:

**Question → Authenticate → Query API → Present Results → Suggest Next Actions**

There are two execution paths for the "Query API" step:

1. **Preferred: `hawkop` CLI** — a single binary that wraps the StackHawk API with
   human and JSON output, response caching, and built-in pagination/auth.
   Most operations collapse to one command. See [`references/hawkop-shortcuts.md`](references/hawkop-shortcuts.md).
2. **Fallback: raw REST calls** — use when `hawkop` is not installed, when you need
   an endpoint `hawkop` doesn't wrap, or when the user explicitly asks for curl.
   See [`references/api-auth.md`](references/api-auth.md) and
   [`references/api-endpoints.md`](references/api-endpoints.md).

Always try `hawkop` first. It authenticates, handles token refresh, follows
pagination, and produces stable JSON — eliminating most of the boilerplate in the
raw-API path.

---

## Step 1: Assess Context

Before making any calls, check what's available:

1. **Is `hawkop` installed and configured?**
   ```bash
   command -v hawkop >/dev/null && hawkop status
   ```
   - If `hawkop status` reports a valid org and JWT → use the **hawkop path** below.
   - If `hawkop` is installed but not configured → run `hawkop init` (interactive).
   - If `hawkop` is not installed → use the **raw API path**. Optionally mention
     `hawkop` as a productivity option (install docs:
     [docs.stackhawk.com/hawkop/](https://docs.stackhawk.com/hawkop/)), but do not
     block on installing it.

2. **Is `hawkop` authenticated?** For local/agentic use, `hawkop init` stores credentials
   in local config — no env var needed. Verify:
   ```bash
   hawkop status
   ```
   > **CI/CD only:** If running in a pipeline, set `HAWKOP_API_KEY` as a secret.
   > The raw API path requires `HAWK_API_KEY` set in the environment.

3. **Is `orgId` known?** Required for most endpoints.
   - With `hawkop`: `hawkop org get` returns the active org UUID. `hawkop org set <ID>` switches the default.
   - With raw API: extract it from the login response (`jq -r '.organization.id'`
     on `/auth/login`) and `export ORG_ID=<uuid>`.

4. **Route based on user intent:**

   | User says... | Go to... |
   |---|---|
   | "What's my security posture?" or "dashboard" | Step 3 (org summary) |
   | "Tell me about [app]'s findings" or "what needs attention" | Step 4 (app deep dive) |
   | "What apps haven't been scanned recently?" | Step 3 with stale-app focus |
   | "What changed since last week?" or "what's new" | Step 4 with diff recipe |
   | "Show me untriaged findings" | Step 3, then drill into Step 4 for flagged apps |

---

## Step 2: Authenticate

### Preferred — `hawkop`

`hawkop init` once for interactive setup — the CLI stores credentials locally and handles token refresh and `401` retry on every call. No further auth work for this skill.

→ Full setup commands (Homebrew install, headless env vars, profiles for org switching): [`references/hawkop-shortcuts.md`](references/hawkop-shortcuts.md#setup-once).

### Fallback — raw API

If `hawkop` isn't available, see [`references/api-auth.md`](references/api-auth.md) for the authentication flow, token management, and helper script.

---

## Step 3: Org Posture Summary

**Goal:** Give the user a bird's-eye view of security health across all apps and environments.

### Tool choice

This step is the one place where the raw API beats `hawkop`: `/api/v2/org/{orgId}/envs` returns per-environment untriaged counts in a single call, and `hawkop` does not yet wrap that endpoint. Use the raw endpoint below.

A `hawkop`-only approximation (app-level view, not per-env) exists — see [`references/hawkop-shortcuts.md`](references/hawkop-shortcuts.md#1--org-posture-summary) §1 for when that's acceptable. Either way, use `hawkop app list --format json` to resolve `applicationId` → app name when presenting the table.

### Canonical endpoint (raw API)

```
GET /api/v2/org/{orgId}/envs
```

Use this endpoint because it returns **untriaged finding counts baked in** per environment —
no need to fetch individual scans just to get severity totals.

```bash
hawk_api GET "/api/v2/org/${ORG_ID}/envs?pageSize=100"
```

### Present as a table

Format the response as:

| App | Environment | High | Medium | Low | Last Scan |
|-----|-------------|------|--------|-----|-----------|
| My API | Production | 3 | 7 | 12 | 2024-01-15 |
| Auth Service | Staging | 0 | 2 | 4 | 2024-01-10 |

Fields: `applicationId` (resolve to app name via apps endpoint — or
`hawkop app list --format json`), `environmentName`, `lastScanHighUntriaged`,
`lastScanMediumUntriaged`, `lastScanLowUntriaged`, `lastScanTimestamp`.

### Flag priority items

- **Stale apps**: `lastScanTimestamp` older than 30 days — flag as "No recent scan"
- **High severity hotspots**: environments with `lastScanHighUntriaged > 0`, sorted descending
- **Incomplete apps**: `lastScanStatus` not `COMPLETED` — may indicate config issues

### After presenting the table

Offer to drill down on any flagged app:
- "App X has 3 unaddressed High findings — shall I pull the full finding details?"
- → Step 4 for any app the user selects

Full recipe with jq transforms:
→ [`references/reporting-recipes.md`](references/reporting-recipes.md)

Full endpoint field reference:
→ [`references/api-endpoints.md`](references/api-endpoints.md) (Section 3: Environments)

---

## Step 4: App Deep Dive

**Goal:** Get specific finding details for a single app — what was found, where, and what it means.

### Preferred — `hawkop` (one command)

`hawkop scan get` walks the scan → alerts → findings chain internally. No manual drill-down, no ID extraction, no token handling. Two patterns cover ~90% of cases:

```bash
# Latest scan for an app — overview + alerts table
hawkop scan get --app "<APP_NAME>"

# Full findings with HTTP evidence + remediation (best for AI agent reasoning)
hawkop scan get --app "<APP_NAME>" --detail full --format json
```

`--detail full` returns every alert, every affected URI, HTTP messages (subject to `--max-body-size`), and remediation guidance in one JSON blob.

→ Specific scan IDs, single-alert / single-URI drill-down, `--max-findings` tuning: [`references/hawkop-shortcuts.md`](references/hawkop-shortcuts.md#2--app-deep-dive-scan--alerts--findings) §2.

### Fallback — raw API drill-down chain (3 calls)

When `hawkop` is not available, there is no single endpoint that returns full
finding details. Follow this chain:

```
Step 1: List scans     GET /api/v1/scan/{orgId}          → extract scanId
Step 2: List alerts    GET /api/v1/scan/{scanId}/alerts   → extract pluginId
Step 3: List findings  GET /api/v1/scan/{scanId}/alert/{pluginId}
```

**Step 1 — Get the most recent scan for the target app:**
```bash
# List scans, filter to the target appId, take the most recent
hawk_api GET "/api/v1/scan/${ORG_ID}?pageSize=50" | \
  jq --arg app "${APP_ID}" \
    '[.applicationScanResults[] | select(.applicationId == $app)] | first'
```
Extract: `scanId`, `highAlertCount`, `mediumAlertCount`, `lowAlertCount`, `startedTimestamp`

**Step 2 — Get alerts for that scan:**
```bash
hawk_api GET "/api/v1/scan/${SCAN_ID}/alerts"
```
Extract per alert: `pluginId`, `alertName`, `severity`, `affectedUriCount`, `cweId`

**Step 3 — Get affected paths per alert:**
```bash
hawk_api GET "/api/v1/scan/${SCAN_ID}/alert/${PLUGIN_ID}"
```
Extract per finding: `uri`, `method`, `status` (triage state; see hawkscan skill `references/platform-model.md` §3 for values), `parameter`

### Present findings

Show a structured summary:
- **Scan summary**: date, duration, total alerts by severity
- **Alert breakdown**: alert name, severity, CWE, number of affected paths
- **Finding details**: for High severity — affected URI, HTTP method, parameter, triage status

Link to the scan on the platform:
```
https://app.stackhawk.com/scans/{scanId}
```

### "What changed?" — diff recipe

Compare two scans: fetch the two most recent scanIds for the app, pull alerts for each, diff the `pluginId` sets — new alerts are those in scan N but not scan N-1.

→ Executable recipe (`hawkop` pipeline with `comm` diff): [`references/hawkop-shortcuts.md`](references/hawkop-shortcuts.md#2--app-deep-dive-scan--alerts--findings) §2.
→ Raw API version: [`references/reporting-recipes.md`](references/reporting-recipes.md).
→ Endpoint field reference: [`references/api-endpoints.md`](references/api-endpoints.md) §4.

---

## Step 5: Present Results and Suggest Next Actions

### Formatting

- Use **tables** for multi-app/multi-finding summaries
- Use **structured lists** for single-app deep dives
- Include the platform link (`app.stackhawk.com/scans/{scanId}`) whenever referencing a specific scan
- Show triage status (`NEW`, `FALSE_POSITIVE`, `RISK_ACCEPTED`, `ASSIGNED`) alongside each finding

### Next action suggestions

Base suggestions on what the data shows:

| Finding | Suggested action |
|---|---|
| High severity findings present | Recommend immediate remediation; offer to hand finding details to → hawkscan skill for a re-scan to verify fixes |
| Stale apps (no scan > 30 days) | Recommend running a fresh scan → hawkscan skill |
| Clean results across all envs | Note that low path count may mean the spider needs tuning → hawkscan skill, config-patterns reference |
| Untriaged findings (`status: NEW`) | Direct to platform for triage: **app.stackhawk.com** — triage write operations are out of scope for this skill |
| `ENV_INCOMPLETE` app status | Direct to platform to complete environment configuration |

### Platform UI vs API data

**Use API data (this skill) when:**
- Generating a bulk posture report across many apps
- Comparing findings across scans programmatically
- Building a CI/CD gate decision from scan output

**Direct to platform UI when:**
- Triaging individual findings (accept, mark false positive)
- Managing API keys, team membership, or app configuration
- Viewing request/response evidence for a specific finding (or use `hawkop scan get <SCAN_ID> --uri-id <ID> --message`)

---

## Common Mistakes to Avoid

- **Don't reach for curl first when `hawkop` is available** — `hawkop scan get --detail full --format json` replaces the three-call drill-down chain and handles auth automatically. Use the raw API only for endpoints `hawkop` doesn't expose (e.g., `/api/v2/org/{orgId}/envs`) or when `hawkop` is not installed.
- **Don't hardcode API keys in scripts** — always reference `${HAWK_API_KEY}` in raw API calls and store credentials via `hawkop init` for CLI use; never inline the key value itself.
- **Don't skip the drill-down chain on the raw path** — there is no single raw endpoint that returns full finding details. Scans → Alerts → Findings is mandatory when not using `hawkop`.
- **Don't confuse `orgId` with `appId`** — `/api/v1/scan/{orgId}` takes the org UUID, not the app UUID. Mixing these returns empty results, not an error. `hawkop scan list --app <APP_ID>` avoids the confusion entirely.
- **JWT expires in 30 minutes** — if you get a `401` mid-session on the raw path, re-authenticate and replay the failed request. The helper script handles this automatically. `hawkop` handles it silently.
- **Don't attempt triage via API** — triage write operations (accept, false positive) are not in scope for this skill. Direct users to the platform UI at app.stackhawk.com.
- **Don't report "no findings" without checking path count** — an empty findings list may mean the spider didn't crawl enough routes. Low path count on a scan is a coverage gap, not a clean bill of health. Recommend spider tuning via → hawkscan skill.
- **Don't mix `hawkop` and raw API output in the same response** — they both serialize JSON from the same upstream data, but `hawkop` may add a `{data: [...], meta: {...}}` envelope. Pick one tool per query and stay consistent.
