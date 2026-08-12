---
name: api
version: 2.4.0
description: >
  Use this skill when a user or agent needs to query the StackHawk platform for
  security reporting, findings analysis, or app management. Triggers include:
  "stackhawk api", "security posture", "findings report", "show me findings",
  "untriaged findings", "which apps", "scan history", "security dashboard",
  "triage", "what needs attention". Uses the hawk CLI (`hawk op` subcommand) for
  all platform queries. Do NOT use for running scans (use the hawkscan skill for
  "scan my app", "hawkscan", "stackhawk.yml", "DAST") or for fixing/remediating
  code or vulnerabilities — this skill only reads and reports platform data.
---

# StackHawk API Skill

This skill enables Claude to act as a security reporting agent against the StackHawk
platform. The core workflow is:

**Question → Authenticate → Query API via `hawk op` → Present Results → Suggest Next Actions**

All platform queries run through the `hawk` binary's `op` subtree
(`hawk op …`). It authenticates, refreshes tokens, follows pagination, and
emits stable JSON. There is no raw-REST fallback — if `hawk` is unavailable,
install it and run `hawk init --browser` rather than hand-rolling curl.
See [`references/hawk-op-shortcuts.md`](references/hawk-op-shortcuts.md).

---

## Step 1: Assess Context

Before making any calls, check what's available:

1. **Is `hawk` installed and configured?** (`hawk version` reports v6.0.0 or greater)
   ```bash
   # Identify the driving skill for CLI usage telemetry (read by hawk/hawkop).
   export _STACKHAWK_SKILL=api
   command -v hawk >/dev/null && hawk op status
   ```
   - valid org + JWT → proceed.
   - installed but unconfigured → `hawk init --browser` (interactive; the combined binary
     has no `hawk op init` — `hawk init` writes `~/.hawk/hawk.properties`, which
     `hawk op` reads along with the `HAWK_API_KEY` env var).
   - not installed → instruct the user to install the `hawk` CLI (docs:
     [docs.stackhawk.com](https://docs.stackhawk.com)) and stop; do **not** fall back to curl.

2. **Is `hawk op` authenticated?** For local/agentic use, `hawk init --browser` stores
   credentials in `~/.hawk/hawk.properties` — no env var needed for interactive
   sessions. Verify:
   ```bash
   hawk op status
   ```
   > **CI/CD only:** If running in a pipeline, set `HAWK_API_KEY` as a secret.
   > `hawk op` reads it directly — no config file required.

3. **Is `orgId` known?** Required for most endpoints.
   - `hawk op org get` returns the active org UUID.
   - `hawk op org set <ID>` switches the default org.

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

`hawk init --browser` once for interactive setup — the CLI stores credentials in
`~/.hawk/hawk.properties` and `hawk op` handles token refresh and `401` retry on
every call. No further auth work for this skill.

→ Full setup commands (install, CI env var, profiles for org switching):
[`references/hawk-op-shortcuts.md`](references/hawk-op-shortcuts.md#setup-once).

---

## Step 3: Org Posture Summary

**Goal:** Give the user a bird's-eye view of security health across all apps and environments.

### Approach

Use `hawk op app list` and `hawk op scan list` to assemble an org-level view.
`hawk op app list --format json` returns app metadata; `hawk op scan list --format json`
returns per-scan severity counts. Join on `applicationId` to build a posture table.

```bash
# All apps with metadata (team, type, env count)
hawk op app list --format json

# Recent scans across the org — has per-scan severity counts
hawk op scan list --limit 500 --format json
```

Fields available per scan: `highAlertCount`, `mediumAlertCount`, `lowAlertCount`,
`applicationId`, `environmentName`, `startedTimestamp`, `status`.

### Present as a table

Format the response as:

| App | Environment | High | Medium | Low | Last Scan |
|-----|-------------|------|--------|-----|-----------|
| My API | Production | 3 | 7 | 12 | 2024-01-15 |
| Auth Service | Staging | 0 | 2 | 4 | 2024-01-10 |

Resolve `applicationId` → app name via `hawk op app list --format json`.

### Flag priority items

- **Stale apps**: `startedTimestamp` older than 30 days — flag as "No recent scan"
- **High severity hotspots**: environments with `highAlertCount > 0`, sorted descending
- **Incomplete scans**: `status` not `COMPLETED` — may indicate config issues

### After presenting the table

Offer to drill down on any flagged app:
- "App X has 3 unaddressed High findings — shall I pull the full finding details?"
- → Step 4 for any app the user selects

Full recipe with jq transforms:
→ [`references/reporting-recipes.md`](references/reporting-recipes.md)

---

## Step 4: App Deep Dive

**Goal:** Get specific finding details for a single app — what was found, where, and what it means.

### `hawk op scan get` (one command covers ~90% of cases)

`hawk op scan get` walks the scan → alerts → findings chain internally. No manual drill-down, no ID extraction, no token handling.

```bash
# Latest scan for an app — overview + alerts table
hawk op scan get --app "<APP_NAME>"

# Full findings with HTTP evidence + remediation (best for AI agent reasoning)
hawk op scan get --app "<APP_NAME>" --detail full --format json
```

`--detail full` returns every alert, every affected URI, HTTP messages (subject to
`--max-body-size`), and remediation guidance in one JSON blob.

→ Specific scan IDs, single-alert / single-URI drill-down, `--max-findings` tuning:
[`references/hawk-op-shortcuts.md`](references/hawk-op-shortcuts.md#2--app-deep-dive-scan--alerts--findings) §2.

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

Compare two scans: use `hawk op scan list` to get the two most recent scan IDs for
the app, pull alerts for each via `hawk op scan get`, diff the `pluginId` sets.

→ Executable recipe (`hawk op` pipeline with `comm` diff):
[`references/hawk-op-shortcuts.md`](references/hawk-op-shortcuts.md#2--app-deep-dive-scan--alerts--findings) §2.
→ Full jq recipes: [`references/reporting-recipes.md`](references/reporting-recipes.md).

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
- Viewing request/response evidence for a specific finding (or use `hawk op scan get <SCAN_ID> --uri-id <ID> --message`)

---

## Common Mistakes to Avoid

- **Don't hardcode API keys in scripts** — always reference `${HAWK_API_KEY}` for CI/CD; store credentials via `hawk init --browser` for local use; never inline the key value itself.
- **Don't confuse `orgId` with `appId`** — `hawk op scan list --app <APP_ID>` takes the app UUID. The org is implicit from config; override with `--org <ID>` if needed. Mixing them returns empty results, not an error.
- **Don't attempt triage via API** — triage write operations (accept, false positive) are not in scope for this skill. Direct users to the platform UI at app.stackhawk.com.
- **Don't report "no findings" without checking path count** — an empty findings list may mean the spider didn't crawl enough routes. Low path count on a scan is a coverage gap, not a clean bill of health. Recommend spider tuning via → hawkscan skill.
- **Don't forget `--detail full` when you need the remediation/HTTP message payload.** The default `hawk op scan get` output is the overview — it won't include per-URI evidence.
