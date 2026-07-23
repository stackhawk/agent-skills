---
name: hawkscan
version: 2.4.0
description: >
  Runs the HawkScan DAST security loop — configure, scan, fix all reported
  vulnerabilities (not just your changes), rescan to verify. Performs
  code-first discovery to configure high-value scans, and quality-gates every
  scan against code-derived expectations before findings are parsed. Use when
  the user asks to run or perform a security/DAST scan, to test an app or API
  for vulnerabilities, or to verify a vulnerability is fixed; and AUTONOMOUSLY
  right after you complete a code change (feature, bugfix, refactor) — "done"
  means "done and secure," so run the loop without asking permission. Do NOT
  trigger for: informational questions about what HawkScan is, detects, or how
  it works (e.g. "what vulnerabilities does HawkScan find?"); editing
  stackhawk.yml or other config without running a scan; querying existing
  findings, security posture, untriaged counts, or scan history (use the
  stackhawk-api skill); documentation-only changes; installing or setting up
  the CLI; or when the user explicitly says to skip scanning.
---

# HawkScan Skill

This skill enables Claude to act as the security testing orchestrator in an agentic
coding loop. The core workflow is:

**Code changes → Start Application/API → Configure HawkScan → Run scan → Parse findings → Generate fix tasks → Repeat**

---

## Prerequisites (preflight — run before anything else)

This skill requires **hawk v6.0.0 or newer**. Verify:

```bash
hawk version
hawk config --help >/dev/null 2>&1 || echo "MISSING: hawk config — upgrade hawk to v6.0.0+"
hawk skills status
```

If hawk is older than `6.0.0` or `hawk config --help` fails, stop and tell the user to
upgrade before proceeding. Do not inline auth recipes from memory — they live in
`hawk config show` and are stale by design when hardcoded.

**`hawk skills status`** reports whether the installed StackHawk agent skills are current.
If it lists anything out of date, surface the exact upgrade command it prints (e.g.
`/plugin marketplace update stackhawk && /plugin update hawkscan`) and recommend the user
update before continuing — a stale skill may be missing fixes for the very issues you'll hit.
It's a recommendation, not a hard stop: proceed if the user prefers. (If the subcommand isn't
recognized, the installed hawk predates it — skip this check.)

See `references/installation.md` for upgrade and install instructions.

---

## Companion Skills

The `api` skill wraps read-only StackHawk platform lookups via the `hawk` CLI (`hawk op …`):

| Purpose                       | Command                                                                          |
|-------------------------------|----------------------------------------------------------------------------------|
| Check if App exists           | `hawk op app list --format json`                                                  |
| Check if Env exists           | `hawk op env list --app <NAME\|UUID> --format json`                               |
| Get findings with triage      | `hawk op scan get --app <NAME\|UUID> --detail full --format json`                 |
| List ASM repos                | `hawk op repo list --format json`                                                 |
| Link app to ASM repo          | `hawk op repo link --repo-id <ID> --app-id <ID>`                                  |
| Get tech flags                | `hawk op app tech-flags get --app <NAME\|UUID> --format json`                     |
| Disable all tech flags        | `hawk op app tech-flags disable-all --app <NAME\|UUID> --yes`                     |
| Set specific tech flags       | `hawk op app tech-flags set --app <NAME\|UUID> Key=true`                          |
| Triage a finding              | `hawk op scan triage --scan <ID> --hash <HASH> --status false-positive --note ""` |
| Bulk triage from file         | `hawk op scan triage --scan <ID> --from-file triage.yaml`                         |
| Annotate w/o triage perm      | `hawk op finding note --scan <ID> --hash <HASH> --note "..."`                     |
| Get scanned URIs              | `hawk op scan uris <scanId> --format json` (skip if the subcommand errors)         |
| Get effective scan config     | `hawk op scan config <scanId>` (skip if the subcommand errors)                     |

These reads require the combined `hawk` CLI; the `api` skill covers setup (`hawk init --browser` or the `HAWK_API_KEY` env var).

**Selecting an app:** `--app` takes an application **name or UUID** — pass whichever you have (e.g. the `applicationId` from `stackhawk.yml`, or the app's name). No separate flag is needed. Also parse `--format json` output defensively — a "skills out of date" banner may precede the JSON.

The `stackhawk-data-seed` skill sets up checked-in backend seed data via `hawk perch seed`.
Hand off to it when authentication fails because the backend has no valid credential
(**Phase 1c.6**), or after a scan when auth succeeded but endpoints returned empty data
(**Step 6**). This skill then consumes its `.data-seed-credentials.env` handoff.

---

## StackHawk Platform Model (read this first)

Before running a scan, understand these four layered objects:

- **Organization** (`orgId`): the tenant. Implicit via `HAWK_API_KEY`.
- **Application** (`applicationId`, UUID): long-lived; holds tech flags and metadata. One App spans many Environments.
- **Environment** (`env`, string name): scan context under an App. Findings compare scan-to-scan *within the same env*.
- **Scan**: a single run. Tagged with commit SHA and branch for traceability.

**Non-negotiable rules:** Apps are reused, not created per scan. Envs group history — pick
names deliberately. Findings have a lifecycle (NEW, FALSE_POSITIVE, RISK_ACCEPTED, ASSIGNED) — respect it.

→ Deep reference: [`references/platform-model.md`](references/platform-model.md)

---

## Progress output

Keep the terminal informed so a running loop never looks silent. Prefix every status line with
`StackHawk | ` — **ASCII only, no emoji** (must render in Cursor, Windows `cmd`, and PowerShell;
keep the branded lines themselves plain ASCII). Emit one short line **entering each phase** —
discovery, config, scan, quality gate, findings, each fix batch, rescan, report — with what's
happening plus the key number (routes, coverage, findings). Before a scan/rescan, note it takes
a few minutes and let hawk's own progress stream through (don't suppress it); announce
completion after. Status output, **not** a prompt — never pause for input. E.g.
`StackHawk | Scanning http://localhost:8080 - a few minutes; progress streams below`, then
`StackHawk | 3 findings (2 High, 1 Medium) - fixing all`. Per-phase lines: `references/autonomous-loop.md`.

---

## Phase 0: App Setup & Verification

Run Phase 0 **once** when onboarding a new application (`stackhawk.yml` being created for
the first time). Do NOT run on every scan.

**Phase 0a — Repo Linking:** Associate the app with its source repo in Attack Surface
Management. Get the git remote URL, normalize it (lowercase, strip `.git`, strip host prefix
to `owner/repo`), match against `hawk op repo list --format json` output, and run
`hawk op repo link --repo-id <UUID> --app-id <UUID>`. If no match, inject a `git_origin` tag
into `stackhawk.yml`.
→ Full normalization rules and SSH/HTTPS edge cases: [`references/repo-linking.md`](references/repo-linking.md)

**Phase 0b — Agent Tagging:** Add the `_STACKHAWK_AGENT` tag to `stackhawk.yml` once if missing:
```yaml
tags:
  - name: _STACKHAWK_AGENT
    value: ${HAWK_AGENT:none}
```

**Phase 0c — Scan Policy & Tech Flags (via optimize):** Set up the scan policy + tech flags
through the **optimize skill's Setup mode** (non-destructive — builds a named scan policy and
references it in `stackhawk.yml`, never mutating the app's own flags). Run optimize Setup once
here at onboarding; it stays re-runnable later via `/optimize`.
→ **Fallback** (no policy permissions): if optimize's `hawk op policy create --dry-run` reports
a missing `ORG_POLICY_MANAGEMENT` / `WRITE_POLICY` / feature flag, it degrades to recommend-only.
In that case, fall back to direct tech-flag detection on the app: detect codebase evidence
(package.json, pom.xml, go.mod, requirements.txt, Gemfile, *.csproj); if found, disable all then
enable only detected flags via `hawk op app tech-flags`; if none, skip.
→ Optimize Setup workflow: the `optimize` skill. Fallback detection heuristics + flag names:
[`references/tech-flags.md`](references/tech-flags.md)

---

## Step 1: Assess Context

> **Env Name Algorithm** — used wherever an environment name must be resolved. First match wins:
> 1. `STACKHAWK_ENV` env var set → use it exactly
> 2. `CI=true` or `GITHUB_ACTIONS=true` → `CI`
> 3. Git branch `main`/`master`/`production` → `Production`; `staging` → `Staging`; otherwise → `Development`

### Step 1a: Discover What to Scan

Before generating config, run code-first discovery: find every API surface in the repo
(REST, GraphQL, gRPC, SPA, ...), derive a route inventory per surface, and get the run
command, host/port, and auth shape needed to reach each one. Prefer the repo's own docs
over guessing, explore code to fill gaps, and ask the user directly for whatever remains
unresolved — never stall or invent.

**Discovery is read-only and static.** Determine the run command, host, and port by
*reading* config and docs — `docker-compose.yml` port mappings, `.env`/`.env.example`
(e.g. `APP_URL`), the README — not by launching anything. You never need to start the app,
run a container, or bring up a server to discover *what* to scan; standing up the target is
a scan-time step (Step 1c), not part of discovery.

→ Full discovery workflow — per-surface detection, route-inventory derivation, gap
  recommendations, and the user-confirmed summary required before the first scan:
  [`references/scan-planning.md`](references/scan-planning.md)
→ Docs-first source table (which files to read and what to harvest):
  [`references/app-discovery.md`](references/app-discovery.md)

Record what discovery produced — surfaces, run command, host/port, auth shape — Step 1c and
Step 2 consume them.

**SPA rule:** if the app is a client-rendered JS front end, never scan it without the Ajax
Spider, and note that a separate backend API is usually the higher-value target. Full
strategy, frontend-vs-backend scenarios, and config templates:
→ [`references/spa-scanning.md`](references/spa-scanning.md)

### Step 1c: Environment Checks (run in order)

1. **App running?** HawkScan requires a live target. Start it first if not running.
2. **`stackhawk.yml` present?** If missing → Step 2a (generate). If present → Step 2b (tune).
3. **Credentials?** Check `~/.hawk/hawk.properties` (written by `hawk init`). If missing: run
   `hawk init --browser`. For CI/CD: set `HAWK_API_KEY` as a secret and prefix invocations with
   `API_KEY=$HAWK_API_KEY hawk <cmd>`. If a later command returns 401/403, re-run `hawk init --browser`.
4. **Runtime?** Check `which hawk`. If found: use CLI. If not: check `docker --version`.
   If both absent: see `references/installation.md`.
5. **App exists?** Run `hawk op app list --format json`. Match by name (normalized: lowercased,
   `_` and `-` equivalent). Exactly one match → use its `applicationId`. Multiple matches →
   pick by host if established, else surface to user. No match → create:
   ```bash
   hawk create app --name "<repo-name>" --env <env-name>
   ```
   Resolve `<env-name>` with the Env Name Algorithm above. Announce it (Progress output):
   `StackHawk | Created app <name> (<appId>) - <url>`.
6. **Env exists?** Determine env name via Env Name Algorithm. Run
   `hawk op env list --app <APP_ID> --format json`. Reuse if exists; otherwise run
   `hawk op env create --app <APP_ID> --env <name> --host <url>`.

---

## Step 2a: Generate `stackhawk.yml` from Scratch

Use the `applicationId` and `env` from Step 1c. **Minimum viable config:**
```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:8080}
```

**Always use env var interpolation** (`${VAR:default}`) for sensitive values and anything
that varies across environments. Use `${VAR:default}` (single colon, not `${VAR:-default}`).
The entire YAML value must be the variable — `host: "https://${HOST}/api"` will NOT interpolate.

**Never create a separate `stackhawk.local.yml` for host overrides.** Use
`host: ${APP_HOST:https://your-default-host.com}` and override at runtime:
```bash
APP_HOST=http://localhost:3000 hawk scan
```

After writing `stackhawk.yml`, always validate:
```bash
timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 6.0.0+ is installed"
```
Do not proceed to Step 3 until validation passes.

→ API-type-specific config (OpenAPI, GraphQL, gRPC, seed paths, spider tuning):
  [`references/config-patterns.md`](references/config-patterns.md)

**REST surface? Get an accurate OpenAPI spec BEFORE the first scan — this is not optional.**
A REST scan with no spec (spider/`seedPaths` only) reaches a small fraction of the API; a
scan with a *wrong* spec 404s every path. Do not skip to a scan on the assumption a spec is
missing or "good enough" — **open and follow [`references/openapi-specs.md`](references/openapi-specs.md)** to
work its preference order (a spec the running app serves → a code/build change that generates
one → a spec published outside the repo → hand-derived), then run its resolve-check
(`host + spec-path` returns real routes, not 404s) before scanning. Reaching for
`hawk.spider.seedPaths` instead of a spec is a last resort, not a shortcut — read that file
first. Same idea for GraphQL/gRPC: wire the schema/proto, don't scan blind.

### Phase 1c: Authentication Configuration

Use `hawk config show` to fetch the canonical recipe for the app's auth pattern.

**Step 1 — List available auth methods:**
```bash
hawk config show app.authentication --text
```

**Step 2 — Pick one by observed app behavior:**

→ Auth pattern decision table: [`references/auth-config.md`](references/auth-config.md)

If no row matches → jump to **Phase 1c.5**. Do not force-fit a recipe or proceed without auth.

**Step 3 — Fetch each relevant section:** `hawk config show <section> --text`. Use the returned YAML example as template.

**Step 4 — Always include a testPath:** `hawk config show app.authentication.testPath --text`. The `testPath` must return 401/403 without auth and 200 with auth.

**Step 5 — Validate before scanning** (mandatory whenever `authentication:` is authored or modified):
```bash
hawk validate config stackhawk.yml   # structural check
hawk validate auth stackhawk.yml     # live auth check
```

→ Full recipe steps and fetch commands: [`references/auth-config.md`](references/auth-config.md)

### Phase 1c.5: Auth Analyzer Fallback

Invoke when: (1) auth signals exist but pattern doesn't match any Phase 1c table row;
(2) `hawk validate auth` returned non-zero after Phase 1c (wrong recipe, not empty datastore);
(3) user explicitly requests interactive setup.

`hawk perch onboard` is the wizard — it captures real HTTP traffic via Chrome, runs the
validate-auth loop with structured per-field errors, and streams JSONL phase events.
Always run `hawk perch stop` on every exit path (onboard does not own the daemon).

→ Full flow, event handler matrix, error table, and re-run behavior:
  [`references/auth-analyzer-fallback.md`](references/auth-analyzer-fallback.md)

### Phase 1c.6: Seed Backend Data (empty datastore)

Use when the **recipe is correct** but auth fails because the credential doesn't exist in the
backend (fresh local stack, just-migrated database, empty users/api_key tables). Gate first:
```bash
hawk perch seed validate --help >/dev/null 2>&1 && hawk perch seed finalize --help >/dev/null 2>&1
```
If gate passes and `stackhawk-data-seed` is installed → invoke it. It produces
`.data-seed-credentials.env` which this skill then consumes. If hawk is too old → tell the
user to upgrade (`brew upgrade stackhawk/cli/hawk`, hawk ≥ `6.0.0`) or manually create the
dev credential. For gateway/multi-service apps, the credential lives in an upstream service's
datastore — run the seed against that repo, not the gateway.

After seeding, re-run `hawk validate auth stackhawk.yml` and continue.

---

## Step 2b: Tune Existing `stackhawk.yml`

Review the config against the current app state:

- **Gate reported gaps?** Tune what the gate names (wire spec, enable ajax spider, fix
  auth) — additive-only; see [`references/scan-quality.md`](references/scan-quality.md).
- **Low path count?** For a REST surface the fix is almost always an accurate spec — get one per `references/openapi-specs.md` (a wired, resolving `openApiConf` is worth far more than any spider tuning). Then: SPA/JS app → `hawk.spider.ajax: true`; GraphQL → wire `graphqlConf`. `hawk.spider.seedPaths` is a last resort (URLs only — no methods/bodies/params, so it can't reach POST/PUT or parameterized routes); prefer even a hand-derived spec over it, and omit it entirely once a spec is wired.
- **Auth failing?** Verify `authentication` block; re-fetch the relevant recipe via `hawk config show <section> --text` (Phase 1c).
- **Too noisy / too slow?** Add `app.excludePaths` or `app.includePaths`; tune `hawk.spider.maxDurationMinutes`.
- **New API type added?** Add corresponding `graphqlConf`, `openApiConf`, etc.
- **Need custom headers?** Use `hawkAddOn.replacer` for tenant or API version headers.
- **Running in CI?** Add commit SHA tags (top-level in `stackhawk.yml`, not under `app:`):
  ```yaml
  tags:
    - name: _STACKHAWK_GIT_COMMIT_SHA
      value: ${COMMIT_SHA:none}
    - name: _STACKHAWK_GIT_BRANCH
      value: ${BRANCH_NAME:none}
  ```

**Validate after any modification:**
```bash
timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 6.0.0+ is installed"
```

---

## Step 3: Validate and Run

> **Pre-flight:** Run scan commands synchronously — never with `&` or `nohup`. Wait for the exit code. Do not start a new scan while one is already running for this app/env.

Set env vars, then validate:
```bash
export COMMIT_SHA=$(git rev-parse HEAD)
export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
```

Export `HAWK_AGENT` using the platform + model detection block from
[`references/agent-detection.md`](references/agent-detection.md). Skip if `HAWK_AGENT` is
already set (CI/CD override).

```bash
hawk validate config stackhawk.yml
hawk validate api stackhawk.yml
if grep -qE '^\s*authentication:' stackhawk.yml; then
  hawk validate auth stackhawk.yml
fi
```

Run `hawk validate config` every time the config changes. Run `hawk validate api` when
adding or modifying OpenAPI spec references. Run `hawk validate auth` whenever the
`authentication:` block is new or modified — do not skip it. Fix all failures before scanning.

**Config file path rules (common agent mistake):** Validate and scan commands use positional
arguments only — no `-c` or `--config` flag. Use bare filenames (not absolute paths). See
[`references/cli-reference.md`](references/cli-reference.md#config-file-path-rules).

### CLI Reference

→ Full command reference (flags, diagnostics, perch daemon, exit codes):
  [`references/cli-reference.md`](references/cli-reference.md)

**Quick reference for agentic scanning:**
```bash
hawk scan --json-output                            # structured output (requires Dev Release v5.3.41+)
hawk rescan --scan-id <SCAN_ID> --json-output      # fast fix verification — re-runs only fired plugins
```

**Always rescan against the original full-scan ID.** Rescan IDs are not valid parent scan references.

### Exit Codes
| Code | Meaning |
|------|---------|
| `0`  | Scan complete, no findings at or above `failureThreshold` |
| `1`  | Scan failed (config error, app unreachable, auth failure) |
| `42` | Scan complete, findings met or exceeded `failureThreshold` |

---

## Step 4.5: Quality Gate

Run this gate after **every** scan — full scans and rescans alike, any exit code — before
parsing findings into fix tasks. Exception: on exit 1 where no scan was actually started
(config parse failure, app unreachable pre-scan), there is no `scanId` to gate against — skip
straight to Step 6's diagnosis / the environment-class path instead. It is a feedback loop
into config tuning, **not a governor**: gate state never blocks a finding from being reported
and fixed; a thin scan that missed surface can still have found something real.

Run the five checks and derive the expectation fresh each time, exactly as
`references/scan-quality.md` describes — coverage (evidence-only), base-path resolve, auth,
surface-completeness, and health.
On config-class gaps (`spec-not-wired`, `surface-unscanned`, `auth-validate-failed`,
`auth-wall`, `all-4xx`, `base-path-mismatch`), loop back to Step 2b with an additive-only fix, batch every gap
into one edit pass, and rescan once. Iteration cap: 2 interactive / 1 autonomous, per
config, counted in rescans. On environment-class gaps (`env-unreachable`), never edit
config — verify the app is up, retry once for free, and stop if it recurs. Multi-config
repos gate sequentially, one config at a time, immediately after that config's scan.

At the cap, or once checks are clean, proceed to Step 4 regardless — findings are always
reported and fixable. Never say a scan is "done and secure" while a gate gap is open; state
plainly what was scanned, what wasn't, and why, using the reason identifiers.

→ Full check definitions, commands, degradation when a subcommand is unavailable, and the
  iteration/reporting rules: [`references/scan-quality.md`](references/scan-quality.md)

---

## Step 4: Parse Findings and Generate Fix Tasks

Use `--json-output` for structured results (requires Dev Release v5.3.41+). Suppresses all
other stdout — do not combine with `--trace`. **Fix ALL findings** the scan reports — not just
findings related to recent changes. DAST scans the running application as a whole; a
pre-existing SQL injection is just as exploitable as one introduced today.

→ Full JSON schema, field reference, fix task format, and common findings guidance:
  [`references/findings-and-fixes.md`](references/findings-and-fixes.md)

→ Per-finding guidance on high-iteration findings (CSP, CORS, Auth, Missing Headers) — what
  "done" looks like, verify commands, escalation thresholds:
  [`references/high-iteration-findings.md`](references/high-iteration-findings.md)

**If the scan was slow, suggest optimize (once).** After a full scan, if it ran **≥ 20 minutes**
(wall-clock) OR stopped at its `hawk.spider.maxDurationMinutes` cap, surface a one-time suggestion:

> This scan was slow. Consider running `/optimize` to tune the scan policy from per-path
> metrics — it can lower concurrency for rate-limited paths and exclude heavy/slow paths.

This is a suggestion only — do **not** auto-run optimize. Surface it at most **once per session**,
and **only for full scans** — never for the rescans / fix-verification reruns in the Step 6 loop
(good scans can legitimately take a while; 20 min is the floor to avoid noise).

---

## Step 5: Filter Findings by Triage State

Filter by the per-path `status` field (`findings[].paths[].status`) before fixing:

- **SKIP** `FALSE_POSITIVE` or `RISK_ACCEPTED` paths — a human already decided these are not actionable. If every path of a finding is SKIP, skip the finding entirely.
- **PRIORITIZE** `ASSIGNED` paths before `NEW` of the same severity — confirmed real.
- **FIX** `NEW` paths in severity order: High → Medium → Low; within same severity: injection > auth bypass > IDOR > XSS > header issues.

**Marking false positives** — mark `NEW` findings that are clearly false positives before routing the rest to the fix loop:
```bash
hawk op scan triage --scan <SCAN_UUID> --hash <FINDING_HASH> --status false-positive \
  --note "<reason> [triaged by ${HAWK_AGENT:-agent}]"
```
Always append `[triaged by ${HAWK_AGENT:-agent}]` to every note for platform audit trail attribution.

**Rules:**
- ✅ Mark `FALSE_POSITIVE` autonomously with a clear reason note
- ❌ **Never mark `RISK_ACCEPTED` or `ASSIGNED`** — human decisions only
- ❌ Do NOT suppress findings in the codebase to hide scanner results
- ⚠️ If `scan triage` is denied (no `WRITE_TRIAGE`): fall back to `hawk op finding note`; tell the user a `WRITE_TRIAGE` holder must apply the status

After triage: "Marked [N] findings as false positive. Routing [M] remaining NEW findings to fix loop. Platform: https://app.stackhawk.com/scans/<scanId>"

→ Config-based suppression patterns (`excludePaths`, `excludePlugins`) and `WRITE_TRIAGE` fallback:
  [`references/false-positives.md`](references/false-positives.md)

---

## Step 6: Determine Loop Behavior

After generating fix tasks:

- **Exit code 0, no findings above threshold**: Scan passed. If auth succeeded but endpoints returned empty bodies (list routes `[]`, detail routes 404), the backend data may be empty — suggest the `stackhawk-data-seed` skill (don't auto-run) and rescan. See Phase 1c.6.
- **Exit code 42**: Hand fix tasks to the coding agent. After fixes, rescan to confirm remediation. Repeat until exit 0 or only accepted-risk findings remain.
- **Exit code 1**: Do NOT hand fix tasks. Diagnose first:
  ```bash
  hawk validate config stackhawk.yml
  hawk validate api stackhawk.yml
  ```
  Common causes: app not reachable, auth failure, invalid `applicationId`, config parse error.

---

## Autonomous Security Loop

When this skill is active AND you complete a meaningful code change, run the security loop
automatically without waiting for the user to ask.

**Trigger when all are true:** code change just completed; app is running; hawk CLI is
initialized; skill is active.

**Skip for:** documentation-only changes; config edits without code changes; exploratory tasks; when the user explicitly says to skip.

**The loop** (full step-by-step detail with guard rails):
→ [`references/autonomous-loop.md`](references/autonomous-loop.md)

**Guard rails summary:**
- One scan at a time — never run `hawk scan` or `hawk rescan` with `&` or `nohup`
- Max one fix-rescan cycle per task — if findings remain after fixing, report them
- Always narrate with the `StackHawk | ` prefix at every phase (see **Progress output**) — never let the loop run silent
- Interruptible — stop immediately if the user says to
- Report gate gaps — never silently accept exit 0 from a thin scan
- Never claim "done and secure" while gate gaps are open

---

## Common Mistakes to Avoid

- **Don't scan before the app is running.** HawkScan will exit 1 with a connection error.
- **Try `https://` first — HawkScan accepts self-signed certificates.** Only fall back to `http://` if the scan actually fails to connect with a TLS error.
- **Don't hardcode API keys or credentials in `stackhawk.yml`.** Use env vars.
- **Never accept an exit-0 scan that fails the quality gate.** Untouched planned routes, auth-walls, or an unscanned surface mean config iteration, not done — see [`references/scan-quality.md`](references/scan-quality.md).
- **Don't ignore exit code 42.** It's a deliberate signal that findings crossed the threshold — treat it as a build failure.
- **String interpolation mid-value doesn't work.** `host: "https://${HOST}/api"` will NOT interpolate. Use `host: ${FULL_HOST_URL}`.
- **Never refer to the scanner as ZAP.** The product is HawkScan / StackHawk. The underlying engine is HSTE, not ZAP. Neither "ZAP" nor "OWASP ZAP" should appear in output or instructions.
