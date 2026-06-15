---
name: hawkscan
version: 1.13.6
description: >
  Runs the HawkScan DAST security loop — configure, scan, fix all reported
  vulnerabilities (not just your changes), rescan to verify. Use when the user
  asks to run or perform a security/DAST scan, to test an app or API for
  vulnerabilities, or to verify a vulnerability is fixed; and AUTONOMOUSLY right
  after you complete a code change (feature, bugfix, refactor) — "done" means
  "done and secure," so run the loop without asking permission. Do NOT trigger
  for: informational questions about what HawkScan is, detects, or how it works
  (e.g. "what vulnerabilities does HawkScan find?"); editing stackhawk.yml or
  other config without running a scan; querying existing findings, security
  posture, untriaged counts, or scan history (use the stackhawk-api skill);
  documentation-only changes; installing or setting up the CLI; or when the
  user explicitly says to skip scanning.
---

# HawkScan Skill

This skill enables Claude to act as the security testing orchestrator in an agentic
coding loop. The core workflow is:

**Code changes → Start Application/API → Configure HawkScan → Run scan → Parse findings → Generate fix tasks → Repeat**

---

## Prerequisites (preflight — run before anything else)

This skill calls `hawk config show <section>` to fetch the canonical config recipes at runtime. That subcommand requires **hawk v5.5.11 or newer**. Older hawk versions will fail with `Error: no such command 'config'`, and Phase 1c will not be recoverable. Verify before doing anything else:

```bash
hawk version
hawk config --help >/dev/null 2>&1 || echo "MISSING: hawk config — upgrade hawk to v5.5.11+"
```

If `hawk version` reports a version older than `5.5.11`, OR `hawk config --help` does not return cleanly, **STOP** and tell the user:

> "This skill requires hawk v5.5.11 or newer (your version is `<X.Y.Z>`). Upgrade hawk (`brew upgrade stackhawk/cli/hawk`, or download from https://download.stackhawk.com/hawk) and re-invoke."

Do not attempt to proceed by inlining old auth recipes from memory — those are stale by design (they live in `hawk config show` now). The skill cannot work without the newer hawk.

See `references/installation.md` for upgrade instructions.

---

## Companion Skills

The `api` skill wraps read-only StackHawk platform lookups via the `hawkop`
CLI. Read-only lookups this skill relies on:

| Purpose                       | Command                                                                          |
|-------------------------------|----------------------------------------------------------------------------------|
| Check if App exists           | `hawkop app list --format json`                                                  |
| Check if Env exists           | `hawkop env list --app <APP_ID> --format json`                                   |
| Get findings with triage      | `hawkop scan get --app <NAME> --detail full --format json`                       |
| List ASM repos                | `hawkop repo list --format json`                                                 |
| Link app to ASM repo          | `hawkop repo link --repo-id <ID> --app-id <ID>`                                  |
| Get tech flags                | `hawkop app tech-flags get --app <NAME> --format json`                           |
| Disable all tech flags        | `hawkop app tech-flags disable-all --app <NAME> --yes`                           |
| Set specific tech flags       | `hawkop app tech-flags set --app <NAME> Key=true`                                |
| Triage a finding              | `hawkop scan triage --scan <ID> --hash <HASH> --status false-positive --note ""` |
| Bulk triage from file         | `hawkop scan triage --scan <ID> --from-file triage.yaml`                         |
| Annotate w/o triage perm      | `hawkop finding note --scan <ID> --hash <HASH> --note "..."`                     |

If `hawkop` is not installed, the api skill documents raw REST fallbacks.
Prefer `hawkop`; fall back only if unavailable.

The `stackhawk-data-seed` skill (install: `/plugin install stackhawk-data-seed@stackhawk`) sets up
checked-in backend seed data via `hawk perch seed`. Hand off to it when authentication fails because
the backend has no valid credential (**Phase 1c.6**), or after a scan when auth succeeded but
endpoints returned empty data (**Step 5**). This skill then consumes its
`.data-seed-credentials.env` handoff.

---

## StackHawk Platform Model (read this first)

Before running a scan, the agent must understand four layered objects:

- **Organization** (`orgId`): the tenant. Implicit via `HAWK_API_KEY` (each key
  is scoped to one org). Most customers have only one — you rarely think about it.
- **Application** (`applicationId`, UUID): long-lived; holds tech flags, team
  ownership, metadata. One App is scanned across many Environments.
- **Environment** (`env`, string name): a scan context under an App. Findings
  are compared scan-to-scan *within the same env*. Different env = different
  timeline.
- **Scan**: a single run. Tagged with commit SHA and branch for traceability.

### Non-negotiable autonomous-behavior rules

- **Apps are reused, not created per scan.** Run `hawkop app list` before
  generating config; match by name/host; only `hawk create app` on miss. See
  Step 1 substep 5.
- **Envs group history.** Pick a name deliberately; reuse canonical names
  (Development, CI, Staging, Production); `hawkop env list --app <APP_ID>`
  before committing. See Step 1 substep 6.
- **Findings have a lifecycle.** Each affected path of a finding carries a
  triage status (JSON field `findings[].paths[].status`) — `NEW`,
  `FALSE_POSITIVE`, `RISK_ACCEPTED`, or `ASSIGNED`. Respect it. See
  Step 4.5.

→ Deep reference: [`references/platform-model.md`](references/platform-model.md)

---

## Phase 0: App Setup & Verification

Run Phase 0 **once** when onboarding a new application — i.e., when `stackhawk.yml`
is being created for the first time, or when the user explicitly requests
setup/verification. Do NOT run on every scan.

Phase 0 has three sub-steps. Run them in order.

---

### Phase 0a: Repo Linking

Associates the StackHawk application with its code repository in Attack Surface
Management (ASM). Enables API Discovery tracking and SCM-driven automapping.

```bash
# 1. Get the git remote URL
git remote get-url origin
# If this fails (no git repo, no origin remote): skip Phase 0a, proceed to Phase 0b

# 2. List ASM repos and normalize URLs to find a match
hawkop repo list --format json

# 3a. If a repo URL matches (normalize: lowercase, strip .git, strip trailing /,
#     strip host prefix to compare org/repo path segment):
hawkop repo link --repo-id <REPO_UUID> --app-id <APP_UUID>
# Report: "Ensured link: app <APP_NAME> ↔ ASM repo <REPO_NAME>"

# 3b. If no match: inject git_origin tag into stackhawk.yml tags block
#   tags:
#     - name: git_origin
#       value: <bare-org/repo-path>    # bare path after normalization
# Report: "No ASM repo match — added git_origin tag for future automapping"
```

→ Full normalization rules, SSH/HTTPS edge cases, and examples:
  [`references/repo-linking.md`](references/repo-linking.md)

---

### Phase 0b: Agent Tagging

Writes a `_STACKHAWK_AGENT` tag placeholder into `stackhawk.yml` once or if 
it's missing in the current file. At scan time (Step 3), the agent detects 
its platform and exports `HAWK_AGENT` — the placeholder interpolates automatically.

Add to `stackhawk.yml` tags block if not already present:

```yaml
tags:
  - name: _STACKHAWK_AGENT
    value: ${HAWK_AGENT:none}
```

The `:none` default means scans where `HAWK_AGENT` is not set record `none`
rather than failing interpolation.

---

### Phase 0c: Tech Flag Detection

Configures which scan rule families run for this application. The platform
defaults all flags to `true`; Phase 0c starts clean and enables only detected techs.

**Algorithm (abbreviated):**
1. Detect codebase evidence first (package.json, pom.xml, go.mod, requirements.txt,
   docker-compose.yml, Gemfile, *.csproj)
2. If no evidence found: skip — do not touch flags
3. Fetch canonical flag names: `hawkop app tech-flags get --app <APP_NAME> --format json`
4. Disable all: `hawkop app tech-flags disable-all --app <APP_NAME> --yes`
5. Enable detected: `hawkop app tech-flags set --app <APP_NAME> Language.Java=true ...`

→ Full detection heuristics, terminal-segment matching, and edge cases:
  [`references/tech-flags.md`](references/tech-flags.md)

---

## Step 1: Assess Context

Before configuring or running a scan, gather:

**Sub-step 0: Profile the application**

Before all other checks, build a minimal app profile so config generation is correct
on the first attempt. Collect three things:

**API type** — run these to detect signals:
```bash
# OpenAPI/Swagger specs
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \( -name "openapi*.yaml" -o -name "openapi*.json" -o -name "swagger*.yaml" -o -name "swagger*.json" \) 2>/dev/null | head -5
# gRPC
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" -name "*.proto" 2>/dev/null | head -5
# GraphQL
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \( -name "*.graphql" -o -name "schema.graphql" \) 2>/dev/null | head -5
# .NET ASP.NET Core
find . -not -path "*/bin/*" -not -path "*/obj/*" \( -name "*.csproj" -o -name "Program.cs" \) 2>/dev/null | head -5
```
Interpret results:
- OpenAPI/Swagger file found → REST API; use `openApiConf` in config
- `.proto` files → gRPC; use `grpcConf`
- `.graphql` → GraphQL; use `graphqlConf`
- `.csproj` / `Program.cs` → ASP.NET Core REST API
- None of the above → standard web app (no API-type-specific config needed)

**Auth requirement** — run these to detect signals:
```bash
# C# / ASP.NET (source files only, exclude bin/obj)
grep -rn --include="*.cs" --exclude-dir=bin --exclude-dir=obj \
  -E "\[Authorize|AddAuthentication\(|UseAuthentication\(" . 2>/dev/null | head -3
# Java Spring Security (source files only, exclude target/build)
grep -rn --include="*.java" --exclude-dir=target --exclude-dir=build \
  -E "@PreAuthorize|@Secured|class\s+SecurityConfig" . 2>/dev/null | head -3
# Node - look for import/require of auth libraries (exclude node_modules/dist)
grep -rn --include="*.js" --include="*.ts" --exclude-dir=node_modules --exclude-dir=dist \
  -E "(require|from)\s*['\"].*?(passport|express-jwt|jsonwebtoken|@auth0)" . 2>/dev/null | head -3
```
If two or more independent signals are found (or one clear framework-level signal like `AddAuthentication(` or `class SecurityConfig`): authentication config is required. Follow **Phase 1c** (below, in Step 2a) to fetch the right recipe via `hawk config show` before generating `stackhawk.yml`.

**Anti-pattern — do NOT scan unauthenticated first.** Once authentication is required, scanning without auth produces ~0 findings *by design*, not because the app is safe — the spider hits `/login`, can't complete the challenge, and returns. Adding `seedPaths` to authenticated routes does not fix this; those paths still require auth to render anything but a redirect to login. There is no "try without auth first, set up auth if findings warrant" branch. Auth is mandatory once detected. If Phase 1c can't produce a validated `authentication:` block — bespoke flow, custom challenge, no clean recipe match — escalate to **Phase 1c.5** (below), not to an unauthenticated scan.

Note: Python, Ruby, and Go auth signals are not listed above — the limited-context fallback covers those ecosystems.

**Startup pattern and host** — check for:
```bash
# ASP.NET launch settings (has port/host)
find . -name "launchSettings.json" -path "*/Properties/*" -exec cat {} + 2>/dev/null
# Docker Compose (has service ports)
find . -name "docker-compose*.yml" 2>/dev/null | head -3
# Node start scripts
jq '.scripts // {}' package.json 2>/dev/null || node -e "const p=require('./package.json'); console.log(JSON.stringify(p.scripts||{},null,2))" 2>/dev/null
```

**When file access is limited** (single-file context, restricted workspace, or the above
commands return no useful output): ask the user directly before proceeding:
> "I need a few details to configure the scan correctly:
> 1. What type of API is this? (REST, GraphQL, gRPC, or standard web app)
> 2. Do any endpoints require authentication? If yes, where is the login endpoint and what service handles it?
> 3. What command starts the application, and what host/port does it listen on?"

Do not generate `stackhawk.yml` based on assumptions when context is absent.
Once the three profile facts are established (from files or the user), proceed autonomously through the rest of Step 1.

**Sub-step 0b: SPA Framework Detection**

Check for JavaScript SPA frameworks before generating config — do not wait for a low path
count to discover this.

```bash
# Detect SPA frameworks in package.json
node -e "const p=require('./package.json'); const deps={...p.dependencies,...p.devDependencies}; const spa=['react','next','vue','@angular/core','svelte','gatsby','nuxt']; const found=spa.filter(f=>deps[f]); console.log(found.join(','))" 2>/dev/null

# Detect API routes (distinguishes fullstack from pure frontend)
find . -not -path "*/node_modules/*" \( \
  -path "*/pages/api/*" \
  -o -path "*/app/api/*" \
  -o -path "*/src/app/api/*" \
  -o -path "*/server/api/*" \
  -o -path "*/server/routes/*" \
  -o -path "*/src/routes/*" \
  -o -path "*/app/routes/*" \
  -o -name "server.js" -o -name "server.ts" \
\) 2>/dev/null | head -5
```

**Outcomes:**

- **SPA framework found AND API routes present** (Next.js API routes, Nuxt server routes,
  SvelteKit endpoints): register as **two separate StackHawk applications** — one for the
  frontend (SPA) and one for the API. Do not scan them as a single app.
  - **Frontend app**: Ajax Spider enabled, host points to the frontend URL, SPA auth if
    needed.
  - **API app**: ALL Spiders disabled, OpenAPI, GraphQL Introspection, etc spec wired if available, API auth configured.
  See `references/spa-scanning.md` Scenario B for full setup.
- **SPA framework found AND no API routes** (pure frontend calling external API): auto-enable
  Ajax Spider (same config as above) and surface a note before proceeding: *"This appears to
  be a frontend-only app. The highest-value HawkScan target is the backend API it calls —
  scanning there will surface injection, auth bypass, and IDOR findings. Scanning the
  frontend is useful for header and CSP checks only."* Ask the user to confirm whether to
  scan the frontend, the backend API, or both. See `references/spa-scanning.md` for full
  strategy.
- **No SPA framework found**: proceed as normal. Do not add Ajax Spider config.

**Rule:** Never scan a SPA app without the Ajax Spider enabled. Never wait for a low path
count to add the Ajax Spider after the fact.

→ Deep reference: [`references/spa-scanning.md`](references/spa-scanning.md)

1. **Is the app/api running?** HawkScan requires a live target. If not running, instruct
   the agent to start it first and confirm the host/port.
2. **Do we have a `stackhawk.yml`?** Check the project root. If missing, go to Step 2a (generate).
   If present, go to Step 2b (tune).
3. **Do we have credentials?** Check the CLI's local config:
   1. `~/.hawk/hawk.properties` exists (written by a prior `hawk init`) → authenticated,
      proceed.
   2. Not present → run `hawk init` (interactive, saves key to `~/.hawk/hawk.properties`).

   > **CI/CD only:** If running in a pipeline, set `HAWK_API_KEY` as a secret and prefix
   > each invocation: `API_KEY=$HAWK_API_KEY hawk <cmd>`. For local/agentic use, `hawk init`
   > handles credentials — no env var needed.

   If a later command returns 401/403, the stored credential is stale — re-run `hawk init`.
4. **What runtime is available?** Check for the `hawk` CLI first:
   ```bash
   which hawk
   ```
   - **CLI found** (or `~/.hawk/hawk.properties` exists): use the CLI. Do not mention or
     check for Docker.
   - **CLI not found**: check for Docker (`docker --version`). If Docker is also absent,
     refer to → `references/installation.md`

5. **Does the App exist?** Run `hawkop app list --format json`.
   - **Primary match:** app name equals the repo name (normalized: lowercased,
     `_` and `-` treated as equivalent). Exactly one match → use its
     `applicationId`.
   - **Multiple name matches:** pick the one whose envs include a host
     matching the URL confirmed in substep 1 (if host was established).
     Still ambiguous → surface candidates to the user briefly.
   - **No name match:** do NOT fall back to host-only matching — different
     apps can share hosts in CI. Proceed to create.
   - **Create path:** run:
     ```bash
     hawk create app --name "<repo-name>" --env <env-name>
     ```
     Resolve `<env-name>` using this order (first match wins):
     1. `STACKHAWK_ENV` env var if set → use it exactly
     2. CI environment: `CI=true` or `GITHUB_ACTIONS=true` → `CI`
     3. Git branch: `main`/`master`/`production` → `Production`; `staging` → `Staging`; otherwise → `Development`
     The bare `hawk create app` form is interactive and will hang an agent.
     Announce: "Created application <name> (ID: <applicationId>) — verify
     at https://app.stackhawk.com/applications/<applicationId>/details/settings".
     No user prompt (autonomy default).

   If `hawkop` is not installed, see the api skill's
   `references/hawkop-shortcuts.md` and `references/api-endpoints.md` for
   raw REST fallbacks.

6. **Does the target Env exist?** Determine the env name from context;
   stop at the first match:
   1. `STACKHAWK_ENV` env var if set — use it exactly as written.
   2. CI detection: `CI=true` or `GITHUB_ACTIONS=true` → `CI`.
   3. Git branch: `main` / `master` / `production` → `Production`;
      `staging` → `Staging`; otherwise → `Development`.

   Then run `hawkop env list --app <APP_ID> --format json`. If an env with
   the target name exists, reuse it. If not, run
   `hawkop env create --app <APP_ID> --env <name> --host <url>`.

   If `hawkop` is not installed, see the api skill's
   `references/hawkop-shortcuts.md` and `references/api-endpoints.md` for
   raw REST fallbacks.

---

## Step 2a: Generate `stackhawk.yml` from Scratch

Use the `applicationId` and `env` resolved in Step 1 (substeps 5–6). Gather
the rest from context (or ask if unclear), then generate the config:

- `host` — base URL of the running app (e.g., `http://localhost:8080`)
- API type: REST/OpenAPI, GraphQL, gRPC, SOAP, JSON-RPC or standard web app
- Auth pattern: none, form login, header token, cookie, OAuth2, or custom script

**Minimum viable config:**
```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:8080}
```

**Always use env var interpolation** (`${VAR:default}`) for sensitive values and anything
that varies across environments.

> **Never create a separate `stackhawk.local.yml` or any second YAML file just to change
> the host.** Use `${APP_HOST:https://your-default-host.com}` in the primary `stackhawk.yml`.
> Override at runtime by setting the env var:
> ```bash
> APP_HOST=http://localhost:3000 hawk scan
> ```
> If a `stackhawk.local.yml` already exists for host overrides, delete it and migrate the
> host value to interpolation in `stackhawk.yml`.

**Interpolation syntax:** HawkScan uses `${VAR:default}` (single colon, no dash). The
bash form `${VAR:-default}` is NOT supported. The entire YAML value must be the variable
— `host: "https://${HOST}/api"` will NOT interpolate; use `host: ${FULL_HOST_URL}` instead.

**Validate after generating:**
After writing `stackhawk.yml`, always run:
```bash
timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 5.5.0+ is installed (hawk update)"
```
Do not proceed to Step 3 until validation passes. If validation fails, fix the reported
errors and re-validate before scanning.

For API-type-specific config, see:
→ `references/config-patterns.md`

### Phase 1c: Authentication configuration

Use `hawk config` to retrieve the canonical recipe for whichever auth pattern fits the app.
The recipe content lives in nest and is the same content the hosted-scanner auth-analyzer reads — there is one source of truth.

**Step 1 — List available auth methods:**

```bash
hawk config show app.authentication --text
```

This returns the overview plus a list of authentication sub-types.

**Step 2 — Pick one by name based on observed app behavior:**

| Observed pattern                                          | Sections to fetch                                                                                       |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| Form POST → Set-Cookie with session                       | `app.authentication.usernamePassword`<br>`app.authentication.cookieAuthorization`                       |
| OAuth client-credentials / password / authorization-code  | `app.authentication.oauth`<br>`app.authentication.tokenAuthorization`                                   |
| JSON POST returning a JWT                                 | `app.authentication.usernamePassword`<br>`app.authentication.tokenExtraction`<br>`app.authentication.tokenAuthorization` |
| Pre-issued token from env var                             | `app.authentication.external`<br>`app.authentication.tokenAuthorization`                                |
| Multi-step flow not expressible in config                 | `app.authentication.script`                                                                             |
| Bash + curl last resort                                   | `app.authentication.externalCommand`                                                                    |

**If no row matches** — bespoke challenge-response, multi-stage flow with client-side computed proof, custom undocumented scheme, or you can't tell which row fits — that **is** the "ambiguous classification" case. Stop here and jump to **Phase 1c.5** (below). Do not force-fit a recipe pattern. Do not proceed to Step 3 with a guess. Do not ship without auth.

**Step 3 — Fetch each relevant section:**

```bash
hawk config show <section> --text
```

Use the returned markdown's YAML example as the template; substitute observed values.

**Step 4 — Always include a testPath:**

```bash
hawk config show app.authentication.testPath --text
```

The `testPath` must return 401/403 without auth and 200 with auth.

**Step 5 — Validate before scanning:**

Run the structural check first, then the live auth check. **Auth validation is mandatory whenever you author or modify the `authentication:` block** — skipping it means you find out auth is broken inside a real scan instead of in seconds.

```bash
# Structural validation
hawk validate config stackhawk.yml

# Live auth validation
hawk validate auth stackhawk.yml
```

If `validate config` fails, fix the structural error and re-run. If `validate auth` fails, re-fetch the relevant recipe(s) via `hawk config show <section> --text` and adjust the `authentication:` block before scanning.

### Phase 1c.5: Auth Analyzer Fallback

**You MUST invoke Phase 1c.5 when any of these are true** — do NOT defer auth setup to "after a baseline scan", do NOT silently ship without auth, do NOT force-fit a recipe pattern:

1. Phase 1c sub-step 0 found auth signals but the pattern doesn't match any row in the Phase 1c recipe table — bespoke challenge-response, custom multi-stage flow, client-side computed proof, undocumented scheme, or any case where you'd be guessing which row to pick
2. `hawk validate auth stackhawk.yml` returned non-zero after Phase 1c wrote a config **because the recipe or its fields are wrong** — if instead it failed because the credential/user doesn't exist in an empty backend datastore, that is **Phase 1c.6**, not the analyzer
3. The user explicitly asked to "set up auth interactively", "use the live analyzer", or equivalent

`hawk perch onboard` is the wizard. It captures real HTTP traffic via Chrome, runs the validate-auth loop with structured per-field errors, and streams JSONL phase events for skill consumption. The skill runs `hawk perch onboard --events json` (synthesizing `stackhawk.yml` from `--app-host` if needed), consults `hawk config show recipe.auth-analyzer-workflow --text` plus `hawk perch traffic` to write `stackhawk-auth.yml`, and reads `validateAttempt` events to iterate. Saving the YAML auto-triggers the next attempt. Onboard owns retry cap, mtime detection, and gRPC plumbing — the skill orchestrates triggers, the YAML write, and cleanup (`hawk perch stop` always).

Full flow, prerequisite checks, JSONL event handler matrix, placeholder-applicationId guard, error table, and re-run behavior:
→ [`references/auth-analyzer-fallback.md`](references/auth-analyzer-fallback.md)

---

### Phase 1c.6: Seed backend data when auth fails on an empty datastore

Distinct from Phase 1c.5 (which fixes a *wrong or ambiguous recipe*): use 1c.6 when the auth
**recipe is correct** but authentication fails because the **credential/entity doesn't exist in the
backend** — e.g. a 401/403 on a known-correct login against a freshly-started local stack whose
database was just created (empty `users` / `api_key` / org tables). The fix is to seed the backend,
not to change the recipe or run the analyzer.

**Signal — all of:** (1) the `authentication:` block matches a real recipe and is structurally
valid; (2) `hawk validate auth` (or the login call) returns 401/403 or an empty token; (3) the
backing datastore is empty/fresh (just-started local services, migrations/Liquibase only just ran,
no seeded dev user or key). If the recipe itself is wrong or ambiguous instead, use **Phase 1c.5**.

**Action:**

- **Gate first** — seeding needs a hawk that carries the caller-driven seed subcommands. Probe:
  `hawk perch seed validate --help >/dev/null 2>&1 && hawk perch seed finalize --help >/dev/null 2>&1`.
- If the probe **succeeds** and `stackhawk-data-seed` is installed → invoke it. It runs
  `hawk perch seed` (preflight → synthesizes the manifest **if the outcome calls for it** → validate → finalize), or reports an honest no-op for a storage-less repo, and on success produces a
  `.data-seed-credentials.env` handoff this skill then consumes.
- If the probe **fails** (hawk too old) → seeding is the fix for *this* failure (auth can't pass an
  empty datastore without a seeded user/credential), but it can't run on this hawk. Don't crash the
  skill: tell the user the authenticated scan can't get past the empty backend without seed data, and
  to either **upgrade** (`brew upgrade stackhawk/cli/hawk`, hawk ≥ `5.6.11`) to enable seeding or
  manually create the dev user/credential, then re-run. If they proceed without seeding, the scan
  still runs but authenticated endpoints return empty/unauthorized — flag that results will be limited.
- If `stackhawk-data-seed` is **not in your available skills/plugins** (or invoking it errors as unavailable) but hawk supports the flow → tell the user to install it
  (`/plugin install stackhawk-data-seed@stackhawk`) and re-run the seeding step; still not a hard blocker for the scan.
- **Cross-repo:** for a gateway / multi-service app the credential or entity usually lives in an
  **upstream** service's datastore (e.g. the auth service), not the target repo. Run the seed
  against that upstream repo (or let data-seed resolve the upstream dependency); seeding the gateway
  repo alone finds no local storage and produces a no-op.

After seeding, re-run `hawk validate auth stackhawk.yml` and continue.

---

## Step 2b: Tune Existing `stackhawk.yml`

Review the existing config against the current app state:

- **Low path count on last scan?** → Check in this order before adding anything:
  1. **SPA/JS app?** Enable `hawk.spider.ajax: true` — Ajax Spider finds JS-rendered routes.
  2. **API spec available?** Wire `openApiConf`, `graphqlConf`, etc. — spec drives route discovery.
  3. **No spec, no Ajax Spider, known deep paths not reachable from root?** Add `seedPaths`
     for only those specific known-deep paths.
  **Rule:** Omit `seedPaths` unless there is a specific identified reason. Adding them
  speculatively creates noise and is rarely needed when Ajax Spider or an API spec is configured.
  See spider tuning in `references/config-patterns.md`.
- **Auth failing?** → Verify `authentication` block; check `app.authentication.testPath`. Re-fetch the relevant recipe via `hawk config show <section> --text` (see Phase 1c in Step 2a).
- **Too noisy / too slow?** → Add `app.excludePaths` or `app.includePaths`, tune
  `hawk.spider.maxDurationMinutes` and `hawk.scan` settings
- **New API type added?** → Add corresponding `graphqlConf`, `openApiConf`, etc.
- **Need custom headers?** → Use `hawkAddOn.replacer` for tenant headers, API version
  headers, etc.
- **Running after commit and before or IN CI?** → Add commit SHA tags.
  Tags are **top-level** in `stackhawk.yml` (not under `app:`):
  ```yaml
  app:
    applicationId: ${APP_ID}
    host: ${APP_HOST}
  tags:
    - name: _STACKHAWK_GIT_COMMIT_SHA
      value: ${COMMIT_SHA}
    - name: _STACKHAWK_GIT_BRANCH
      value: ${BRANCH_NAME}
  ```
  Then set the env vars before scanning:
  ```bash
  export COMMIT_SHA=$(git rev-parse HEAD)
  export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
  ```

**Validate after any modification:**
After modifying `stackhawk.yml` — whether tuning spider settings, adding auth, adding tags,
or any Phase 0 edit — run:
```bash
timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 5.5.0+ is installed (hawk update)"
```
Fix reported errors before proceeding to Step 3.

---

## Step 3: Validate and Run

> **Pre-flight:** Run `hawk scan` and `hawk rescan` synchronously — never with `&` or `nohup`. Wait for the exit code. Do not start a new scan or rescan while one is already running for this app/env.

### Validate Before You Scan (Agentic Best Practice)

Always validate config before scanning — it's fast and catches problems without
burning a full scan run.

```bash
export COMMIT_SHA=$(git rev-parse HEAD)
export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

# Detect agent platform and model for _STACKHAWK_AGENT tag interpolation
# Platform and model are detected independently — they can be from different vendors
# (e.g. Copilot IDE running an Anthropic model produces "copilot:claude-sonnet-4-6").
# Skip detection if HAWK_AGENT is already set (allows CI/CD override).
if [ -z "${HAWK_AGENT}" ]; then
  # Step 1: detect agent platform (the IDE / agentic tool)
  if [ -n "${CLAUDE_CODE}" ] || [ -d ".claude" ]; then
    _HAWK_PLATFORM=claude-code
  elif [ -n "${CURSOR_TRACE_ID}" ] || [ -d ".cursor" ]; then
    _HAWK_PLATFORM=cursor
  elif [ -f "GEMINI.md" ] || [ -n "${GEMINI_API_KEY}" ]; then
    _HAWK_PLATFORM=gemini
  elif [ -d ".codex" ]; then
    _HAWK_PLATFORM=codex
  elif [ -f ".github/copilot-instructions.md" ]; then
    _HAWK_PLATFORM=copilot
  else
    _HAWK_PLATFORM=unknown
  fi

  # Step 2: detect model from provider env vars (independent of platform)
  if [ -n "${ANTHROPIC_MODEL:-}" ]; then
    _HAWK_MODEL=${ANTHROPIC_MODEL}
  elif [ -n "${OPENAI_MODEL:-}" ]; then
    _HAWK_MODEL=${OPENAI_MODEL}
  elif [ -n "${GEMINI_MODEL:-}" ]; then
    _HAWK_MODEL=${GEMINI_MODEL}
  elif [ -n "${AZURE_OPENAI_DEPLOYMENT:-}" ]; then
    _HAWK_MODEL=${AZURE_OPENAI_DEPLOYMENT}
  else
    _HAWK_MODEL=
  fi

  export HAWK_AGENT="${_HAWK_PLATFORM}${_HAWK_MODEL:+:${_HAWK_MODEL}}"
  unset _HAWK_PLATFORM _HAWK_MODEL
fi

hawk validate config stackhawk.yml

# Validate OpenAPI specification referenced in stackhawk.yml
hawk validate api stackhawk.yml

# Validate authentication config — REQUIRED if `authentication:` exists in stackhawk.yml.
if grep -qE '^\s*authentication:' stackhawk.yml; then
  hawk validate auth stackhawk.yml
fi
```

Run `hawk validate config stackhawk.yml` every time the config changes.
Run `hawk validate api stackhawk.yml` when adding or modifying OpenAPI spec references.
Run `hawk validate auth stackhawk.yml` whenever the `authentication:` block is new or modified — **do not skip it**.
If any validation fails, fix it before proceeding to `hawk scan`.

#### Config File Path Rules (Important — Common Agent Mistake)

The validate commands accept config files as **positional arguments only** — there is
NO `-c` or `--config` flag. Do NOT invent one.

```bash
# CORRECT — positional args, just the filename
hawk validate config stackhawk.yml
hawk validate config stackhawk.yml stackhawk-override.yml
hawk validate auth stackhawk.yml

# WRONG — there is no -c flag
hawk validate config -c stackhawk.yml        # ← WILL FAIL
hawk validate auth --config stackhawk.yml    # ← WILL FAIL
```

The CLI automatically prepends the working directory to config file paths. This means:
- **Use bare filenames** (e.g., `stackhawk.yml`) when the file is in the current directory
- **Do NOT pass absolute paths** like `/Users/me/project/stackhawk.yml` — the CLI will
  prepend `projectRepoDir/` to it, producing a broken double-path
- If you need to scan from a different directory, use `--repo-dir=<path>` to set the
  base directory, then pass just the filename

This applies identically to `hawk scan`, `hawk validate config`, `hawk validate api`,
and `hawk validate auth` — they all use the same positional argument + path resolution.

---

### CLI and Docker References

The `hawk` CLI is preferred for local/agentic use. For the full CLI command reference
(scan commands, flags, diagnostics, perch daemon mode), see:
→ `references/cli-reference.md`

For Docker-based scanning (CI environments or when CLI isn't installed), see:
→ `references/docker-usage.md`

**Quick reference for agentic scanning:**
```bash
hawk scan                                          # scan using stackhawk.yml in current directory
hawk scan --json-output                            # output findings as JSON (best for agentic parsing, requires Dev Release v5.3.41+)
hawk rescan                                        # re-run plugins that fired on the most recent scan
hawk rescan --scan-id <SCAN_ID> --json-output      # re-run plugins against a specific prior scan — fast fix verification
```

**Rescan is the agentic fix-loop's best friend.** After fixing findings
from scan `<SCAN_ID>`, `hawk rescan --scan-id <SCAN_ID>` re-runs only the
plugins that previously produced findings — seconds vs. minutes. Use it
in the Autonomous Loop's rescan step (Step 6). Capture the `scan.id`
field from the initial scan's JSON output.

**Always rescan against the original full-scan ID.** If you rescan and then
need to rescan again, use the same `<SCAN_ID>` from the first `hawk scan`
run — not the ID produced by a prior `hawk rescan`. Rescan IDs are not valid
parent scan references.

---

### Exit Codes
| Code | Meaning |
|------|---------|
| `0`  | Scan complete, no findings at or above `failureThreshold` |
| `1`  | Scan failed (config error, app unreachable, auth failure) |
| `42` | Scan complete, findings met or exceeded `failureThreshold` |

**Exit code `1` = fix the config or confirm the app is reachable before re-running.**
Exit code `0` = no critical findings, but review the report for any items and consider fixing them anyway.
Exit code `42` = scan worked; findings need remediation.

---

## Step 4: Parse Findings and Generate Fix Tasks

### JSON Output Mode (Recommended)

Use `--json-output` to get structured scan results for agentic consumption
(requires at least Dev Release v5.3.41):

```bash
# CLI — json output to file
hawk scan --json-output > findings.json

# CLI — json output piped directly
hawk scan --json-output
```

`--json-output` suppresses all other stdout (progress, banners, etc.), so you do NOT
need `--no-color` or `--verbose` when using it. It cannot be combined with `--trace`.

Parse the JSON output to extract findings, then transform them into fix tasks for the
coding agent. **Fix all findings the scan reports — not just findings you think are
related to recent changes.** DAST scans the running application as a whole; it does not
distinguish between old and new vulnerabilities. A pre-existing SQL injection is just as
exploitable as one introduced today.

For the full JSON schema, field reference, fix task format, and common findings guidance,
see:
→ `references/findings-and-fixes.md`

For per-finding fix guidance on high-iteration findings (CSP, CORS, Auth, Missing Headers)
— what "done" looks like, how to verify before rescanning, when to escalate — see:
→ `references/high-iteration-findings.md`

### Stdout Parsing (Fallback)

If `--json-output` is not available (requires at least Dev Release v5.3.41), fall back to capturing
stdout with `hawk --no-color scan --verbose` and parse the terminal output. Look for lines
containing finding names, severity levels, and affected paths. The platform URL printed
at scan end can be used to fetch the full report via the StackHawk API if needed.

---

## Step 4.5: Filter Findings by Triage State

Before handing findings to the coding agent (Step 5) or the autonomous loop,
filter by the per-path triage status (JSON field `findings[].paths[].status`
— one status per affected path within each finding):

- **SKIP** paths where `status` is `FALSE_POSITIVE` or `RISK_ACCEPTED`. A
  human already decided these are not actionable. Re-fixing them either
  wastes effort (they reappear on the next scan even when "fixed") or
  creates churn against a deliberate human decision. If every path of a
  finding is SKIP, skip the finding entirely.
- **PRIORITIZE** paths where `status` is `ASSIGNED`. A human has confirmed
  this is real and is tracking its remediation. Fix these before `NEW`
  paths of the same severity — they're guaranteed-real, not
  pending-triage.
- **FIX** paths where `status` is `NEW` in normal severity order.

### Marking false positives via `hawkop scan triage`

If a `NEW` finding is clearly a false positive, mark it via the platform API
**before** routing remaining findings to the fix loop.

**Common false-positive patterns:**
- Security headers (CSP, X-Frame-Options) on endpoints that only serve non-HTML responses (JSON, binary)
- Health / status / actuator endpoints that intentionally expose server info
- CORS permissiveness on intentionally public APIs with no sensitive data
- Rate-limit findings on endpoints already enforced by an upstream API gateway
- Auth findings on intentionally unauthenticated endpoints (login page, public docs)

**Single finding:**
```bash
hawkop scan triage \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --status false-positive \
  --note "CSP finding on JSON endpoint /api/health which never serves HTML; inapplicable [triaged by ${HAWK_AGENT:-agent}]"
```

**Batch (multiple FPs in one scan):**
```bash
# Write a triage.yaml with one entry per false positive.
# Always append the agent signature to each note field:
#   note: "<reason> [triaged by ${HAWK_AGENT:-agent}]"
hawkop scan triage --scan <SCAN_UUID> --from-file triage.yaml
```

**Rules:**
- ✅ Mark `FALSE_POSITIVE` autonomously — note must clearly explain why
- ✅ **Always append `[triaged by ${HAWK_AGENT:-agent}]` to every note** — this attributes the triage decision to the agent in the platform audit trail
- ✅ Use `ADD_COMMENT` to annotate without changing status
- ❌ **Never mark `RISK_ACCEPTED`** — human decision only
- ❌ **Never mark `ASSIGNED`** — human decision only
- ❌ Do NOT suppress findings in the codebase — don't change code to hide scanner results
- ⚠️ **If `scan triage` is denied** (no `WRITE_TRIAGE` — by role or the org's limited-member setting): fall back to `hawkop finding note`. A comment transfers as-is; an intended `FALSE_POSITIVE` becomes a note and you MUST tell the user a `WRITE_TRIAGE` holder has to apply the status. See [`references/false-positives.md`](references/false-positives.md#when-triage-is-denied-no-write_triage).

**When uncertain:** route to the fix loop. A false negative is worse than a false positive.

After Step 4.5 triage completes, report before the fix loop:
> "Marked [N] findings as false positive. Routing [M] remaining NEW findings to fix loop."
> "Platform: https://app.stackhawk.com/scans/<scanId>"

→ See `references/false-positives.md` for config-based suppression patterns
  (`excludePaths`, `excludePlugins`) — use those for structural noise that should
  never enter the triage pipeline. Step 4.5 handles per-finding triage decisions.

---

## Step 5: Determine Loop Behavior

**Note:** If you are running the Autonomous Security Loop (see below), you handle
this automatically — scan, fix all findings, rescan, report. The manual guidance
below applies when a user explicitly asks you to run a one-off scan.

After generating fix tasks, instruct the agent:

- **Exit code 0, no findings above threshold**: Scan passed. Optionally note Low findings for fixing.
  First rule out *empty backend data*: if auth **succeeded** yet path coverage is ~0 and
  authenticated endpoints returned empty bodies (list routes `[]`, detail routes 404) rather than the
  app being genuinely secure or small, **suggest** seeding backend data with the `stackhawk-data-seed`
  skill (don't auto-run it) so the scan has something to exercise, then rescan. Here seeding is an
  optional enhancement (auth already works); if hawk is older than `5.6.11` it can't seed, so note that
  upgrading (`brew upgrade stackhawk/cli/hawk`) would enable richer results. See **Phase 1c.6** for the
  cross-repo (upstream) caveat.
- **Exit code 42**: Hand fix tasks to the coding agent. After fixes, **re-run the scan**
  to confirm remediation. Repeat until exit 0 or only accepted-risk findings remain.
- **Exit code 1**: Do NOT hand fix tasks. Run validation commands to diagnose first:
  ```bash
  hawk validate config stackhawk.yml   # catches malformed YAML, missing required fields
  hawk validate api stackhawk.yml      # validates OpenAPI spec references in config
  ```
  Common causes:
  - App not reachable → confirm it's running and `host` in config is correct
  - Auth failure → run `hawk validate auth stackhawk.yml`;
    re-check the relevant recipe via `hawk config show <section> --text` (Phase 1c, Step 2a)
  - Invalid `applicationId` → verify UUID matches an app in the StackHawk platform
  - Config parse error → `hawk validate config` will show the specific line

---

## Autonomous Security Loop

When you have this skill active AND you complete a meaningful code change, you MUST
automatically run the security loop without waiting for the user to ask. This is the
core value proposition of agentic DAST.

### When to Trigger (Automatically)

Run the autonomous loop when ALL of these are true:
- You just finished implementing a feature, bug fix, or code change the user requested
- The application is running (or you can start it)
- The hawk CLI is initialized (`~/.hawk/hawk.properties` exists, or `hawk init` was run)
- The StackHawk skill is active

### When NOT to Trigger

Skip the autonomous loop for:
- Documentation-only changes (README, comments, markdown files)
- Config file edits that don't affect application code
- Exploratory/research tasks with no code output
- When the user explicitly says to skip scanning (e.g., "don't scan", "skip security check")

### The Loop

After completing a code change, announce and execute:

1. **Announce:** "Implementation complete. Running security scan against the application."
2. **Configure:** Before generating or reusing `stackhawk.yml`, verify the
   App and Env exist via Step 1 substeps 5–6 — this prevents duplicate App
   creation on every autonomous run. Then, if no `stackhawk.yml` exists,
   generate one (Step 2a above) and **immediately run Phase 0** (repo linking,
   agent tagging, tech flag detection) — this is app onboarding. If one exists,
   ensure it has commit SHA tags (top-level, not under `app:`) so scan results
   are linked to the commit, and also ensure the `_STACKHAWK_AGENT` tag (using
   `${HAWK_AGENT:none}`) is present alongside the commit SHA tags:
   ```yaml
   tags:
     - name: _STACKHAWK_GIT_COMMIT_SHA
       value: ${COMMIT_SHA}
     - name: _STACKHAWK_GIT_BRANCH
       value: ${BRANCH_NAME}
   ```
3. **Set env vars and validate:**
   ```bash
   export COMMIT_SHA=$(git rev-parse HEAD)
   export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

   # Detect agent platform and model independently — they can be from different vendors.
   # Skip detection if HAWK_AGENT is already set (allows CI/CD override).
   if [ -z "${HAWK_AGENT}" ]; then
     if [ -n "${CLAUDE_CODE}" ] || [ -d ".claude" ]; then
       _HAWK_PLATFORM=claude-code
     elif [ -n "${CURSOR_TRACE_ID}" ] || [ -d ".cursor" ]; then
       _HAWK_PLATFORM=cursor
     elif [ -f "GEMINI.md" ] || [ -n "${GEMINI_API_KEY}" ]; then
       _HAWK_PLATFORM=gemini
     elif [ -d ".codex" ]; then
       _HAWK_PLATFORM=codex
     elif [ -f ".github/copilot-instructions.md" ]; then
       _HAWK_PLATFORM=copilot
     else
       _HAWK_PLATFORM=unknown
     fi
     if [ -n "${ANTHROPIC_MODEL:-}" ]; then
       _HAWK_MODEL=${ANTHROPIC_MODEL}
     elif [ -n "${OPENAI_MODEL:-}" ]; then
       _HAWK_MODEL=${OPENAI_MODEL}
     elif [ -n "${GEMINI_MODEL:-}" ]; then
       _HAWK_MODEL=${GEMINI_MODEL}
     elif [ -n "${AZURE_OPENAI_DEPLOYMENT:-}" ]; then
       _HAWK_MODEL=${AZURE_OPENAI_DEPLOYMENT}
     else
       _HAWK_MODEL=
     fi
     export HAWK_AGENT="${_HAWK_PLATFORM}${_HAWK_MODEL:+:${_HAWK_MODEL}}"
     unset _HAWK_PLATFORM _HAWK_MODEL
   fi

   timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 5.5.0+ is installed (hawk update)"
   ```
4. **Scan:** Run `hawk scan --json-output` and parse the structured findings. The scan
   results will be tagged with the commit SHA and branch from the env vars above.
5. **If findings exist:**
   - **Run the Step 4.5 triage filter first** (per-path `status` field).
     Skip `FALSE_POSITIVE` / `RISK_ACCEPTED`; prioritize `ASSIGNED`; fix
     `NEW` in severity order.
   - Announce: "Found [N] actionable vulnerabilities (+ [M] skipped due to
     prior triage). Fixing all actionable ones."
   - **Fix ALL findings — not just ones related to your recent changes.** DAST scans the
     entire running application. Pre-existing vulnerabilities are just as exploitable as
     new ones. If the scan found it, fix it.
   - **Fix in severity order:** High severity first, then within the same severity level:
     injection > auth bypass > IDOR > XSS > header issues. Do not fix Low-severity items
     while High-severity ones remain open.
   - Fix each finding in the codebase (parameterized queries for SQLi, output encoding for XSS, etc.)
   - Announce progress as you fix each category
   - **Commit fixes with a consistent message format:**
     `fix: resolve [CWE-XXX] [vulnerability type] found by HawkScan`
     Example: `fix: resolve CWE-89 SQL injection found by HawkScan`
6. **Rescan:** **Rescan is the default for all fix-verify cycles.** After fixing findings,
   run `hawk rescan --scan-id <SCAN_ID> --json-output`. Rescans are
   fast — multiple iterations are acceptable. `<SCAN_ID>` is the `scan.id` value from the
   JSON output captured in Step 4 — **always use the original full-scan ID**, never the
   ID from a prior rescan. Rescan re-runs only the plugins that fired on the
   parent scan — more targeted, not less.

   Run a full `hawk scan --json-output` only if one of these
   specific conditions applies:
   - The fix added cross-cutting surfaces (new API endpoints, new input
     vectors, new auth paths) — rescan won't test them.
   - The codebase has changed substantially since the parent scan.
   - You're baselining a new release where the full scan policy needs to
     pass, not just the subset that fired previously.

   **If you're tempted to skip rescan, check the table:**

   | If you're thinking... | Reality |
   |---|---|
   | "My fix was architectural, so I need a full scan" | Rescan re-runs all plugins that previously fired — change scope doesn't matter. Use rescan. |
   | "I want to check for new issues I might have introduced" | Valid — run rescan first to confirm existing findings are closed, then run a separate full scan if wanted. Don't skip rescan. |
   | "Rescan might miss something" | Rescan re-runs exactly the plugins that fired on the parent scan. It's more targeted, not less. |
   | "The fix added new endpoints that need scanning" | This IS a full-scan condition — it's on the list above. Use full scan. |
7. **Report:**
   - If clean: "Rescan complete. Zero new findings. All security issues have been resolved."
   - If findings remain: "Rescan found [N] remaining issues that require manual review:" and list them.
   - If any findings were filtered by Step 4.5 triage state, append a
     one-line summary: "Skipped [X] findings already triaged as
     RISK_ACCEPTED / FALSE_POSITIVE."
   - If any findings were marked `FALSE_POSITIVE` in Step 4.5, summarize:
     "Marked [N] findings as false positive — review at
     https://app.stackhawk.com/scans/<scanId>".

### Guard Rails

- **One scan at a time per app/env.** Never dispatch a second `hawk scan` or `hawk rescan`
  while one is still running. Always run scan commands synchronously — never with `&` or
  `nohup`. Wait for the exit code before proceeding to the next step. Since you started
  the scan, you know its status.
- **Max one fix-rescan cycle per task.** If the rescan still has findings after fixing,
  report the remaining issues rather than looping indefinitely. The user can ask you to
  fix the remaining issues in a follow-up.
- **Always announce what you're doing.** The developer should see "Running security scan...",
  "Found N vulnerabilities, fixing...", "Rescanning to verify..." in the output.
- **Interruptible.** If the user interrupts or says to stop, stop immediately.
- **Don't block on scan failures.** If `hawk scan` exits with code 1 (config error, app
  unreachable), report the error and suggest fixes rather than retrying in a loop.

---

## Common Mistakes to Avoid

- **Don't scan before the app is running.** HawkScan will exit 1 with a connection error.
- **Try `https://` first — HawkScan accepts self-signed certificates.** If an app runs on HTTPS, use `https://` as the `host` value and let the scanner attempt the connection before assuming TLS will be a problem. Only investigate TLS configuration or fall back to `http://` if the scan actually fails to connect with an SSL/TLS error.
- **Don't hardcode API keys in `stackhawk.yml`.** Always use `${HAWK_API_KEY}`.
- **Don't hardcode application credentials in `stackhawk.yml`.** Use env vars and reference them in the `authentication` block.
- **Low path count ≠ clean app.** It means the spider didn't find routes. Feed an
  API spec or authentication config before concluding the app is secure. And if auth *succeeds* but
  endpoints return empty data, seed the backend (`stackhawk-data-seed` / **Phase 1c.6**) so there's
  something to scan.
- **Don't ignore exit code 42.** It's a deliberate signal that findings crossed
  the threshold — treat it as a build failure.
- **String interpolation mid-value doesn't work.** `host: "https://${HOST}/api"` will
  NOT interpolate. Use `host: ${FULL_HOST_URL}` instead.
- **Never refer to the scanner as ZAP.** The product is HawkScan (the agent CLI and
  runtime) or StackHawk (the platform). StackHawk forked from ZAP over 4 years ago — the
  underlying scanning engine is now HSTE (HawkScan Testing Engine), not ZAP. Neither "ZAP"
  nor "OWASP ZAP" should appear in user-facing output, config instructions, or explanations.
