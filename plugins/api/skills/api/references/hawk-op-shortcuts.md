# hawk op Shortcuts — StackHawk API, one command at a time

Cheat sheet: **user intent → `hawk op` command**. `hawk op --help` and
`hawk op <cmd> --help` are the canonical flag references.

See `SKILL.md` for the full workflow.

---

## Setup (once) {#setup-once}

**Install the combined `hawk` CLI** — a single self-contained binary (no Java needed).

macOS — Homebrew (recommended):

```bash
brew tap stackhawk/cli
brew trust stackhawk/cli
brew install hawk
```

Otherwise resolve the binary from the manifest (the source of truth for the version
and every download URL, `https://download.stackhawk.com/hawkdocs/hawk.manifest.json`):

```bash
# macOS / Linux — resolve the right binary from the manifest, then install
MANIFEST=https://download.stackhawk.com/hawkdocs/hawk.manifest.json
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)              GROUP=darwin-arm64 ;;
  Darwin/x86_64)             GROUP=darwin-x64 ;;
  Linux/x86_64)              GROUP=linux-x64 ;;
  Linux/aarch64|Linux/arm64) GROUP=linux-aarch64 ;;
esac
url=$(curl -fsSL "$MANIFEST" | jq -r --arg g "$GROUP" \
  '.latest.assets[] | select(.asset.group == $g and (.url | endswith("/hawk"))) | .url')
curl -fsSL "$url" -o hawk && chmod +x hawk && sudo mv hawk /usr/local/bin/hawk
```

URL pattern: `https://download.stackhawk.com/hawk/<version>/<group>/hawk[.pkg|.exe|.msi]`
(`<group>`: `darwin-arm64`, `darwin-x64`, `linux-x64`, `linux-aarch64`, `windows-x64`,
`windows-arm64`). macOS `.pkg` and Windows `.msi` installers are also available —
see `https://docs.stackhawk.com/downloads/`.

```bash
hawk init --browser    # Browser device-flow auth; writes ~/.hawk/hawk.properties
hawk op status         # Confirm auth
```

`hawk init` writes credentials to `~/.hawk/hawk.properties`.  
`hawk op` reads that file plus the `HAWK_API_KEY` env var.

**CI/CD only:** For pipeline use, set `HAWK_API_KEY` directly as a secret.
Org ID and output format can be set via env vars:

```bash
export HAWK_API_KEY=<your-api-key>   # from app.stackhawk.com → Settings → API Keys
export HAWK_ORG_ID=<org-uuid>
export HAWK_FORMAT=json

hawk op app list
```

Switching orgs (without rewriting config):

```bash
hawk op --org <OTHER_ORG_ID> scan list   # One-shot override
hawk op profile create customer-a        # Named profile
hawk op -P customer-a app list           # Use a profile per-command
```

---

## §1 — Org posture summary {#1--org-posture-summary}

**User intent:** "What does my security posture look like?" / "Which apps need attention?"

Use `hawk op app list` and `hawk op scan list` to assemble an org-level view:

```bash
# All apps with metadata (team, type, env count)
hawk op app list --format json

# Recent scans across the org — has per-scan severity counts
hawk op scan list --limit 500 --format json
```

Join on `applicationId` with `jq` to get a posture table. You'll have
`highAlertCount`, `mediumAlertCount`, `lowAlertCount` per scan — those are *scan*
counts per scan run. Enrich with `hawk op app list --format json` for app names,
team ownership, etc.

---

## §2 — App deep dive (scan → alerts → findings) {#2--app-deep-dive-scan--alerts--findings}

**User intent:** "Tell me about [app]'s findings" / "What are the High severity
issues in the latest scan?"

`hawk op scan get` walks the entire drill-down chain internally — no manual ID
extraction, no token handling.

### Latest scan for an app (overview + alerts)

```bash
hawk op scan get --app "<NAME|UUID>"    # --app takes a name or a UUID
```

Wraps: `/scan/{orgId}` + `/scan/{scanId}/alerts`. Returns a scan header, alert
counts by severity, and a table of alerts.

### Latest scan for an app, with full findings

```bash
hawk op scan get --app "<APP_NAME>" --detail full --format json
```

Wraps the **entire drill-down chain** plus per-URI HTTP request/response bodies and
the ZAP remediation advice. Best JSON for an AI agent to reason over.

Tune the envelope:
- `--max-findings N` (default 100) — sorted by severity, highest first
- `--max-body-size BYTES` (default 10240) — HTTP response body truncation threshold

### A specific scan by ID

```bash
hawk op scan get <SCAN_ID>                          # Overview + alerts
hawk op scan get <SCAN_ID> --detail full --format json
```

### A single alert (plugin) within a scan

```bash
hawk op scan get <SCAN_ID> --plugin-id 40012
```

Wraps: `/scan/{scanId}/alert/{pluginId}` — returns every affected URI for that alert.

### A single finding with HTTP request/response

```bash
hawk op scan get <SCAN_ID> --uri-id <URI_ID> --message
```

Wraps: `/scan/{scanId}/alert/{pluginId}/uri/{uriId}` with `include=message`.
Returns evidence and the raw HTTP exchange.

### Listing scans (for diff recipes, filters, etc.)

```bash
hawk op scan list                                    # Recent across all apps
hawk op scan list --app <APP_ID> --limit 10         # Last 10 for one app
hawk op scan list --env production --status complete # Combined filters
hawk op scan list --format json                      # For scripting
```

Fields in the JSON match the raw `/api/v1/scan/{orgId}` response — `scanId`,
`applicationId`, `environmentName`, `highAlertCount`, etc.

### Diff recipe — "what changed since last scan?"

```bash
# Two most recent scans for one app as JSON
hawk op scan list --app <APP_ID> --limit 2 --format json > /tmp/last2.json
SCAN_A=$(jq -r '.data[0].scanId' /tmp/last2.json)
SCAN_B=$(jq -r '.data[1].scanId' /tmp/last2.json)

# Pull alerts for each and diff the pluginId sets
hawk op scan get "$SCAN_A" --format json | jq '.alerts[].pluginId' | sort -u > /tmp/a.ids
hawk op scan get "$SCAN_B" --format json | jq '.alerts[].pluginId' | sort -u > /tmp/b.ids

comm -23 /tmp/a.ids /tmp/b.ids    # New in A (not in B)
comm -13 /tmp/a.ids /tmp/b.ids    # Resolved (in B, gone in A)
```

---

## §3 — List endpoints (apps, users, teams, policies, repos, specs, configs, secrets)

All of these are one `hawk op <noun> list` command with identical flag surface:

| Query | `hawk op` command | Raw endpoint |
|-------|-------------------|--------------|
| List applications | `hawk op app list` | `GET /api/v2/org/{orgId}/apps` |
| List apps by type | `hawk op app list --type cloud` | `...?applicationTypes=CLOUD` |
| List scans | `hawk op scan list` | `GET /api/v1/scan/{orgId}` |
| List users / members | `hawk op user list` | `GET /api/v2/org/{orgId}/members` |
| List teams | `hawk op team list` | `GET /api/v1/team/{orgId}/list` |
| List scan policies | `hawk op policy list` | `GET /api/v1/org/{orgId}/policy` |
| List repositories | `hawk op repo list` | `GET /api/v1/org/{orgId}/repos` |
| List OpenAPI specs | `hawk op oas list` | `GET /api/v1/org/{orgId}/oas` |
| List scan configs | `hawk op config list` | `GET /api/v1/org/{orgId}/configs` |
| List user secrets | `hawk op secret list` | `GET /api/v1/user/secrets` |
| List environments | `hawk op env list --app <APP_ID>` | `GET /api/v2/org/{orgId}/envs` |

Common flags on every `list`:

```
-n, --limit N          Max results (caps AFTER all pages are fetched)
-p, --page N           Page (0-indexed); omit to auto-fetch ALL pages
    --page-token TOK   Opaque forward cursor (mutually exclusive with --page)
    --sort-by FIELD
    --sort-dir asc|desc
    --format table|json|pretty
```

By default (no `--page`/`--page-token`) a `list` **auto-follows every page** and
returns the full set — you don't paginate manually. Use `--limit` to cap the rows
(it trims after collection, not a server-side early stop).

---

## §4 — Audit log

**User intent:** "What happened in my org last week?" / "Who started that scan?"

```bash
hawk op audit list --since 7d
hawk op audit list --since 30d --type SCAN_STARTED,SCAN_COMPLETED
hawk op audit list --user "Jane" --email jane@example.com
hawk op audit list --since 2025-01-01 --until 2025-01-31
hawk op audit list --org-type EXTERNAL_ALERTS_SENT,ORGANIZATION_CREATED --limit 200
```

Wraps: `GET /api/v1/org/{orgId}/audit` with server-side filters — no post-filter
`jq` pipeline needed.

Relative dates: `--since 7d`, `--since 30d`, `--since 24h` all work alongside ISO
dates (`--since 2025-01-01`).

---

## §5 — Hosted scan control (start / stop / status)

**User intent:** "Kick off a scan on the platform" / "Is that hosted scan still running?"

```bash
hawk op run start <APP_ID> --env <ENV>    # Start a hosted scan
hawk op run status <SCAN_ID>              # Poll status
hawk op run stop <SCAN_ID>                # Cancel a running scan
```

Wraps: `POST /api/v1/scan`, `GET /api/v1/scan/{scanId}`, `DELETE /api/v1/scan/{scanId}`.

Note: this skill should still route "scan my app running locally" to the
**hawkscan** skill — `hawk op run` is specifically for **cloud/hosted** scans
executed by the StackHawk platform against a URL it can reach.

---

## §6 — Environment management

**User intent:** "Add a staging env to this app" / "Give me the stackhawk.yml
template for this env"

```bash
hawk op env list --app <APP_ID>
hawk op env config --app <APP_ID> --env prod     # Default stackhawk.yml
hawk op env create --app <APP_ID> --env staging --host https://staging.example.com
hawk op env delete --app <APP_ID> --env old-env
```

Wraps: `/api/v2/org/{orgId}/envs` (CRUD) and `/api/v1/org/{orgId}/application/{appId}/environment/{env}/config`.

---

## Output format quick reference

```bash
hawk op app list                      # pretty (human-optimized, default)
hawk op app list --format table       # one row per entry, grep-friendly
hawk op app list --format json        # {data: [...], meta: {...}} envelope
```

When piping to `jq`:

```bash
hawk op app list --format json | jq -r '.data[].name'
hawk op scan list --format json | jq '.data[] | select(.highAlertCount > 0)'
hawk op scan get <ID> --detail full --format json | jq '.findings[].uri'
```

Setting `HAWK_FORMAT=json` once in the shell avoids `--format json` on every
call — useful when building a reporting pipeline.

---

## Common mistakes

- **Don't pass the org UUID where `hawk op` expects an app UUID.** `hawk op scan list --app`
  takes an application ID. The org is already implicit from config; override with
  `--org <ID>` if needed.
- **Don't forget `--detail full` when you need the remediation/HTTP message payload.**
  The default `hawk op scan get` output is the overview — it won't include per-URI
  evidence.
- **`--app` takes a name or a UUID.** A UUID resolves exactly; a name resolves by
  case-insensitive exact match. If a name matches **more than one** app, `hawk op` errors and
  lists the matches — disambiguate by passing that app's UUID to `--app` (grab it from
  `hawk op app list`).
