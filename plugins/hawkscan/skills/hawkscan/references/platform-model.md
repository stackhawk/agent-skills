# StackHawk Platform Model

Deep reference for the object model behind every HawkScan run. Read this
when the primer in `SKILL.md` isn't enough, when you see an unexpected
`findings[].paths[].status` value, or when deciding whether to create a
new App / Env.

## Table of Contents

1. [The Four Objects in Detail](#the-four-objects-in-detail)
2. [What Goes in `stackhawk.yml` (and What Doesn't)](#what-goes-in-stackhawkyml-and-what-doesnt)
3. [The Finding Lifecycle (Triage States)](#the-finding-lifecycle-triage-states)
4. [Tags and Commit Traceability](#tags-and-commit-traceability)
5. [Technology Flags](#technology-flags)
6. [Rescan: Derived Scans for Fast Fix Verification](#rescan-derived-scans-for-fast-fix-verification)
7. [Create vs. Reuse Decision Tree](#create-vs-reuse-decision-tree)
8. [Cross-Reference to the api Skill](#cross-reference-to-the-api-skill)

---

## The Four Objects in Detail

### Organization (`orgId`)

The tenant. A UUID tied to your StackHawk account. Set implicitly by your
`HAWK_API_KEY` (each key is scoped to one org); you rarely reason about it
directly. `hawk op org get` shows the active org.

Most customers have a single org. Multi-org setups exist (consultancies,
MSSPs) — when present, every `hawk op` command accepts `--org <ID>` or uses
named profiles (`hawk op -P <profile> app list`).

**Not in `stackhawk.yml`.** Implicit via auth.

### Application (`applicationId`)

The long-lived object representing "the thing you're scanning." Each App:

- Has a stable UUID (shown as `applicationId` in configs, APIs, everywhere)
- Has a name (human-readable — used for `hawk op app list` lookups)
- Has a team ownership assignment
- Has **technology flags** that shape scan rule selection (see §5)
- Is scanned across one or more Environments

An App lives for the lifetime of the thing you're protecting. Renaming a
repo, refactoring, changing languages — none of these should produce a new
App. New Apps are for genuinely new services.

**In `stackhawk.yml`:** `app.applicationId`.

### Environment (`env`)

A scan context under an App. Identified by a **string name** — not a UUID.
Canonical names: `Development`, `CI`, `Staging`, `Production`. You can use
others, but stick to a small, deliberate set.

Environments group scans for comparison: StackHawk tracks which findings
are new or fixed across successive scans **within the same env**. A finding
that disappears across scans in the Development env is considered resolved
for Development. The same finding in Production is a separate timeline.

**In `stackhawk.yml`:** `app.env`.

### Scan

A single execution of `hawk scan`. Identified by a UUID (`scanId`) returned
by the platform. Scans:

- Are immutable once complete
- Are tied to one App and one Env
- Carry tags (commit SHA, branch, custom CI run IDs)
- Produce findings; each affected path carries a triage `status` field (`findings[].paths[].status`)
- Are viewable at `https://app.stackhawk.com/scans/<scanId>`

You don't configure the Scan object directly — the platform generates it
when you run `hawk scan`. You control its metadata through tags.

**Rescans are child scans.** `hawk rescan --scan-id <parentScanId>` produces
a new Scan object that re-runs only the plugins that fired on the parent.
See §6 for how this turns HawkScan into a fast fix-verification engine
for the agentic loop.

---

## What Goes in `stackhawk.yml` (and What Doesn't)

| In `stackhawk.yml`                                | Not in `stackhawk.yml`                          |
|---------------------------------------------------|-------------------------------------------------|
| `app.applicationId` (UUID)                        | `orgId` (implicit via `HAWK_API_KEY`)           |
| `app.env` (string name)                           | Technology flags (platform UI / API only)       |
| `app.host` (scan target)                          | Triage status (per-finding, platform-side)      |
| `tags` (commit SHA, branch, custom)               | User / team assignments                         |
| API-type config (`openApiConf`, `graphqlConf`, …) |                                                 |
| `authentication` block                            |                                                 |
| Scan tuning (`hawk.spider`, `hawk.scan`)          |                                                 |

**Rule of thumb:** `stackhawk.yml` describes *how to scan*. The App / Env
describe *what's being scanned and who owns it*. Tech flags describe *what
rules are relevant*. Triage describes *what findings mean*. Keep each
concern in its proper layer.

---

## The Finding Lifecycle (Triage States)

Every affected path in the JSON output (`hawk scan --json-output` or
`hawk op scan get --detail full --format json`) carries a triage `status`
field (`findings[].paths[].status`). The canonical values:

- `NEW`
- `FALSE_POSITIVE`
- `RISK_ACCEPTED`
- `ASSIGNED`

### What each state means for the agent

| Value             | What it means                                                                       | Agent action                                                                          |
|-------------------|-------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `NEW`             | Finding detected, not yet triaged by a human                                        | **Fix** in severity order.                                                            |
| `FALSE_POSITIVE`  | Human marked "scanner is wrong" in the platform UI                                  | **Skip.** Re-fixing overrides a human decision.                                       |
| `RISK_ACCEPTED`   | Human marked "this risk is acceptable" in the platform UI                           | **Skip.** Same reasoning.                                                             |
| `ASSIGNED`        | Human confirmed this is real and assigned it for remediation                        | **Prioritize.** Fix before same-severity `NEW` — guaranteed-real, not pending-triage. |

There is no "reopened" state — if a previously-triaged finding reappears
on a later scan, the platform continues to report its current triage
value (`FALSE_POSITIVE` / `RISK_ACCEPTED` stays sticky unless a human
changes it).

### What the agent can write via `hawk op scan triage`

The `hawk op` commands expose triage writes. Use these in Step 5 of the scan
loop when the agent identifies clear false positives.

```bash
# Mark a single finding path as a false positive (--note required)
hawk op scan triage \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --status false-positive \
  --note "CSP finding on JSON endpoint /api/health; never serves HTML"

# Add a comment without changing status
hawk op scan triage \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --status add-comment \
  --note "Reviewed; confirmed false positive pattern"

# Bulk triage from file (up to 100 actions per call)
hawk op scan triage --scan <SCAN_UUID> --from-file triage.yaml
```

**Agent constraints:**
- ✅ May mark `FALSE_POSITIVE` autonomously — must include a detailed `--note`
- ✅ May use `ADD_COMMENT` to annotate findings
- ❌ Must NOT mark `RISK_ACCEPTED` — human decision only
- ❌ Must NOT mark `ASSIGNED` — human decision only
- ❌ Do NOT suppress findings in code — do not change code to hide scanner results

The `--note` is required for `FALSE_POSITIVE` and `ADD_COMMENT`.
It must explain the reasoning clearly enough for a human to review and reverse if wrong.

**If `hawk op scan triage` is denied** — the account lacks `WRITE_TRIAGE`, by role or
because the org's `LIMITED_MEMBER_ROLE` setting turned off member finding-triage —
fall back to `hawk op finding note`, which records a note through an ungated route. A
comment transfers cleanly; an intended `FALSE_POSITIVE` is recorded as a note and the
status change is escalated to a `WRITE_TRIAGE` holder. See `references/false-positives.md`
(linked from SKILL.md Step 5) for the full fallback procedure.

→ Bulk triage file format and false-positive heuristics: see `references/false-positives.md` via SKILL.md Step 5.

### Exact JSON serialization

The values above are the canonical names. JSON serialization should match
exactly (`"status": "NEW"`). If you observe a different format (e.g.,
lowercase or title-case) in real output, treat the values above as
authoritative and file the discrepancy as a platform bug.

---

## Tags and Commit Traceability

Tags are arbitrary key/value pairs attached to a scan. They are how a scan
in the platform UI tells you "this was the run from commit `abc123` on
branch `feat/foo`." Tags are **top-level** in `stackhawk.yml`, not nested
under `app:`.

### Standard tags (recognized by the platform UI)

```yaml
tags:
  - name: _STACKHAWK_GIT_COMMIT_SHA
    value: ${COMMIT_SHA:none}
  - name: _STACKHAWK_GIT_BRANCH
    value: ${BRANCH_NAME:none}
```

These show up in the scan detail view as "Commit" and "Branch" fields.

### Setting the values

Before scanning:

```bash
export COMMIT_SHA=$(git rev-parse HEAD)
export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
```

Or set them in your CI system's env block.

### Custom tags

Anything with a non-underscore prefix is a custom tag. Useful for:

- CI run IDs (`ci_run: ${GITHUB_RUN_ID:none}`)
- Release markers (`release: v2.4.0`)
- Feature flag state (`variant: dark-mode-on`)

Custom tags show up in scan filters and audit logs; they don't drive
platform behavior.

---

## Technology Flags

Technology flags are per-Application metadata that tell HawkScan which
scan rule families to emphasize. A Postgres-flagged App gets the
Postgres-specific SQL injection variants; a React SPA gets
client-rendered-XSS rules; a Spring-flagged Java service gets Spring-aware
framework checks.

### Where they live

**On the Application**, set in the platform UI at:

```
https://app.stackhawk.com/applications/<applicationId>/details/settings
```

**Not in `stackhawk.yml`.** `stackhawk.yml` tells HawkScan *how* to scan
(config); tech flags tell HawkScan *which rules are relevant*. Different
concerns.

### Setting tech flags via `hawk op`

Tech flags are set via the `hawk op` commands during Phase 0 of the scan workflow
(whenever a `stackhawk.yml` is created), as the fallback when the optimize skill cannot
create a scan policy. The process is: disable-all first (to clear the platform's
all-true default), then enable only what codebase evidence supports.

```bash
# 1. Fetch canonical flag list — API is source of truth for valid names
hawk op app tech-flags get --app <APP_NAME> --format json

# 2. Disable all (--yes required for non-interactive/agent use)
hawk op app tech-flags disable-all --app <APP_NAME> --yes

# 3. Enable only detected flags
hawk op app tech-flags set --app <APP_NAME> Language.Java=true Language.Java.Spring=true
```

Phase 0 runs whenever a `stackhawk.yml` is created (new app or reused app), not on every scan.

→ Full detection heuristics, matching algorithm, and edge cases: see `references/tech-flags.md` via SKILL.md Phase 0c.

### Detecting the right flags for a codebase

For context only (not yet actionable): common detection heuristics are

| Evidence                                       | Likely flag(s)                                          |
|------------------------------------------------|---------------------------------------------------------|
| `package.json` → `react` / `next` / `vue`      | React / Next / Vue                                      |
| `pom.xml` / `build.gradle` → Spring Boot       | Java / Spring                                           |
| `requirements.txt` → Django / Flask / FastAPI  | Python / Django / Flask                                 |
| `docker-compose.yml` → `image: postgres:...`   | Postgres                                                |
| Connection strings with `mongodb://`           | MongoDB                                                 |
| `go.mod`                                       | Go                                                      |
| No evidence matched                            | Leave flags unset — platform defaults will apply        |

When the tech-flag API arrives, the skill will do this detection
automatically.

---

## Rescan: Derived Scans for Fast Fix Verification

`hawk rescan --scan-id <parentScanId>` re-runs only the plugins that
produced findings on the parent scan — skipping the rest of the test
suite. This turns HawkScan into a targeted regression engine: verification
of a set of fixes runs in seconds, not minutes.

### When to use rescan

- **Agentic fix loop:** initial `hawk scan` → agent fixes findings →
  `hawk rescan --scan-id <id>` to verify. This is Step 6 of the
  Autonomous Security Loop.
- **Quick "did my fix work?" checks** — local or CI.
- **Tight iteration** on flaky remediation that you're testing repeatedly.

### When to use a full `hawk scan` instead

- **Fixes added new surfaces** — new API endpoints, new input vectors, new
  auth paths. Rescan only tests what previously fired; it will not explore
  the new surface.
- **Substantial codebase change** between scans — the parent scan's plugin
  subset may no longer cover the current risk profile.
- **Release baselines** where the full policy must pass, not just a subset.

### Agent usage pattern

```bash
# Step 1: Initial scan, capture the scan ID
hawk scan --json-output > /tmp/scan.json
INITIAL_SCAN_ID=$(jq -r '.scan.id' /tmp/scan.json)

# Step 2: Fix the findings in /tmp/scan.json's findings[] array

# Step 3: Rescan — re-run only the plugins that fired in the initial scan
hawk rescan --scan-id "${INITIAL_SCAN_ID}" --json-output > /tmp/rescan.json
```

### Triage and tags behavior on rescan

- **Triage state inherits from the parent scan.** A finding that was
  `FALSE_POSITIVE` / `RISK_ACCEPTED` / `ASSIGNED` on the parent remains
  in that state on the rescan (unless a human changed triage between
  scans). Step 5's filter applies to rescan results the same way.
- **Tags do not inherit automatically.** Re-set `_STACKHAWK_GIT_COMMIT_SHA`
  and `_STACKHAWK_GIT_BRANCH` env vars before rescan if the commit
  changed due to fixes — otherwise the rescan will carry the parent's
  commit tag, which is wrong.

### Limitation to know about

Rescan cannot discover new vulnerabilities. If a fix introduces a fresh
vulnerability (e.g., swapping one broken auth scheme for another broken
one on a *new* endpoint), rescan won't catch it — only a full scan will.
The Autonomous Loop's fix-verify cap mitigates this: on the next
full scan, anything rescan missed will surface.

---

## Create vs. Reuse Decision Tree

### Application

```
Is there an existing App for this codebase?
│
├── Run `hawk op app list --format json`
│   │
│   ├── Name match (lowercased, _/- equivalent)?
│   │   │
│   │   ├── Exactly one match  ──► REUSE (use its applicationId)
│   │   │
│   │   └── Multiple matches   ──► Narrow by host match across envs
│   │                               │
│   │                               ├── One survives  ──► REUSE
│   │                               └── Still ambiguous ──► Ask the user
│   │
│   └── No name match          ──► CREATE (`hawk create app`) after the
│                                   team check below. Announce the
│                                   details-settings URL for tech flag setup.
```

### Choosing a team for a new App

A caller without the team-write permission who belongs to two or more teams
cannot create an App without naming a team: the API returns HTTP 400 naming
`teamId` and creates nothing. A creator on exactly one team who names no team
gets the App on that team. A caller with the team-write permission can always
create without a team. So check the teams before every `hawk create app`, but
send `--team-id` only when someone chose a team:

```bash
hawk op team list --format json
# Multi-org: add --org <org-id>, the same org you pass to `hawk create app --org-id`
```

The JSON is `{"data": [{"id", "name", "users", "apps"}, ...], "meta": {...}}`.
Parse from the first `{` — a "skills out of date" banner may precede it. The
list shows the teams you can put the App on. Its scope depends on the
READ_ALL_APPLICATIONS permission, not on the role name: without it you see only
your own teams; with it you see every org team and may create into any of them.

| Teams in `data` | Create with |
|-----------------|-------------|
| 0 or 1 | `hawk create app --name "<app-name>" --env <env-name>` (no `--team-id`) |
| 2+, someone can answer | Ask which team, listing the names plus "Don't pick a team (you'll get your only team if you're on exactly one; otherwise the app has no team and the whole org can see it)"; then `... --team-id <chosen-team-id>`, or no `--team-id` for "Don't pick a team" |
| 2+, headless (CI, autonomous run with no one to answer) | No `--team-id`, so keys with the team-write permission keep working; on the `teamId` 400, see below |

**Announcing the team.** `hawk create app` does not print the team, and
`hawk op app list`/`app get` carry no team field, so read the team back:

| How the App was created | Team to announce |
|-------------------------|------------------|
| With `--team-id` | That team |
| No `--team-id`, team list had exactly 1 team | Run `hawk op team get <that-team-id> --format json`; if the new appId is in `.data.applications[].applicationId`, that team; if it is not, none |
| No `--team-id`, team list had 0 teams | None |
| Anything else (team list or `team get` failed, or 2+ teams and no team chosen) | Unknown |

Announce `StackHawk | Created app <name> (<appId>) on team <team> - <url>`, or
`on team none` when it has no team. When the team is unknown, drop the team
part and never claim the whole org can see the App: say only that it was
created, and that the server puts it on the creator's team when they are on
exactly one.

**Failures — never retry blindly:**

- **HTTP 400 that mentions `teamId`** — the caller is on several teams and
  must pick one. Interactive: explain that and ask which team again, this
  time without the "Don't pick a team" option. Headless: stop and report the team names
  and IDs, and that a team must be chosen before the App can be created.
  Never pick one.
- **`Invalid team ID provided`** — `hawk create app` checked `--team-id`
  against `GET /org/{org}/user/{user}/teams` and refused it; no App was
  created. That endpoint has the same READ_ALL_APPLICATIONS scope as
  `hawk op team list`, so any team from the list passes unless membership or
  permissions changed. Explain, list the teams again, and ask. Do not retry
  the same ID or switch to another team on your own.
- **`hawk op team list` itself fails** (for example a permission error for a
  scan-only service-account key) — create without `--team-id`. If that returns
  the `teamId` 400, stop and tell the user to pass a team ID (the StackHawk UI,
  or `hawk op team list` run with their own credentials, shows it).

Credentials come from the same place as every other `hawk` call
(`~/.hawk/hawk.properties`, or the `API_KEY=$HAWK_API_KEY` prefix in a
headless session). Never put a literal API key on a command line.

This applies only to creating an App. Reusing an existing App never changes
its team.

### Environment

```
Is there an existing Env for this scan context?
│
├── Determine target name:
│     STACKHAWK_ENV  →  CI detection  →  branch-based default
│
├── Run `hawk op env list --app <APP_ID> --format json`
│   │
│   ├── Target name exists  ──► REUSE
│   └── Target name missing ──► CREATE (`hawk op env create ...`)
```

### Changing `applicationId` mid-project

**Don't.** Changing `applicationId` in an existing `stackhawk.yml` orphans
the scan history — the platform shows a hard break, "findings fixed" vs.
"findings new" can't be computed across the cutover, and the old App
becomes a stale shell. Requires explicit human sign-off to do.

Symptoms that *feel* like "I need a new App" but usually aren't:

- Repo was renamed → keep the App, optionally rename it in the UI
- New branch with major refactor → keep the App, scan in a different env
- New microservice split off → that *might* be a new App (new service =
  new ownership)

---

## Cross-Reference to the api Skill

This skill uses the `api` skill's `hawk op` wrappers for read-only platform
lookups. Relevant commands and their documentation:

| Purpose                       | Command                                                    |
|-------------------------------|------------------------------------------------------------|
| List apps                     | `hawk op app list --format json`                            |
| List envs for an app          | `hawk op env list --app <APP_ID> --format json`             |
| Get scan findings with triage | `hawk op scan get --app <NAME\|UUID> --detail full --format json` |

These reads require the combined `hawk` CLI; the `api` skill covers setup (`hawk init --browser` or the `HAWK_API_KEY` env var).
