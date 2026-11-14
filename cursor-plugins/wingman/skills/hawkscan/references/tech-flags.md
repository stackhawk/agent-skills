# Tech Flags Reference

Auto-detect your application's technology stack and configure StackHawk tech flags accordingly.

> **When this applies:** This direct app-tech-flag detection is the **fallback** for hawkscan
> Phase 0c — used only when the optimize skill can't create a scan policy (missing
> `ORG_POLICY_MANAGEMENT` / `WRITE_POLICY` / feature flag). The preferred path is the optimize
> skill's Setup mode (a non-destructive named scan policy). The heuristics below are unchanged
> and apply to both.

## Contents
- [Overview](#overview)
- [Command Reference](#command-reference)
- [Flag Name Rules](#flag-name-rules)
- [Phase 0c Detection Algorithm](#phase-0c-detection-algorithm)
- [Detection Heuristics](#detection-heuristics)
- [Matching Detected Techs to Canonical Flag Keys](#matching-detected-techs-to-canonical-flag-keys)
- [Example: Detect and Configure a Node.js + React + PostgreSQL App](#example-detect-and-configure-a-nodejs--react--postgresql-app)
- [No Match Policy](#no-match-policy)
- [Manual Override](#manual-override)
- [Troubleshooting](#troubleshooting)

---

## Overview

The StackHawk platform defaults **all tech flags to `true`**, which enables scanning for all rule families regardless of relevance. This creates unnecessary noise and slower scans.

**Agentic best practice:** Disable all flags first, then enable only the technologies detected in the codebase. This approach:
- Reduces false positives (no rules for tech you don't use)
- Improves scan speed (fewer rule families to evaluate)
- Produces more precise findings (cleaner reports)

Flag names are **dot-namespaced** (e.g., `Language.Java.Spring`), **case-sensitive**, and sourced from the StackHawk API. The API is the **only source of truth** for valid flag names — never hardcode them.

---

## Command Reference

### Fetch canonical flag list

```bash
hawk op app tech-flags get --app <APP_NAME> --format json
```

`--app <NAME|UUID>` accepts either the application name or its UUID — pass whichever you have.

Returns a JSON object with all available flags and their current true/false state:

```json
{
  "Language.JavaScript": false,
  "Language.JavaScript.React": false,
  "Language.JavaScript.NextJs": false,
  "Language.Java": false,
  "Language.Java.Spring": false,
  "Db.PostgreSQL": false,
  "Db.MySQL": false
}
```

**Use this output to validate flag names before calling `set`.**

### Disable all flags (reset to baseline)

```bash
hawk op app tech-flags disable-all --app <APP_NAME> --yes
```

Flips all flags to `false` in one operation. The `--yes` flag is **required** in non-interactive contexts (scripts, agents); omit it for interactive use (will prompt for confirmation).

**Important:** If the API returns an empty flag list (no flags defined yet), skip this step and proceed directly to detection.

### Enable detected flags

```bash
hawk op app tech-flags set --app <APP_NAME> \
  Language.Java=true \
  Language.Java.Spring=true \
  Db.PostgreSQL=true
```

The `set` command performs a **partial update**: only the provided keys change; others stay as they are.

**Value syntax:**
- Enable: `KEY=true`, `KEY=1`, `KEY=on`, `KEY=yes`
- Disable: `KEY=false`, `KEY=0`, `KEY=off`, `KEY=no`

### Preview before committing

```bash
hawk op app tech-flags set --app <APP_NAME> \
  Language.Java=true \
  Language.Java.Spring=true \
  --dry-run
```

Shows what would change without applying the update.

---

## Flag Name Rules

- **Dot-namespaced:** `Language.Java`, `Language.Java.Spring`, `Db.PostgreSQL`
- **Case-sensitive:** `Language.Java` ≠ `language.java`
- **API is source of truth:** Always validate flag names via `hawk op app tech-flags get` before using them in `set` commands
- **Parent namespace inclusion:** When enabling a child flag (e.g., `Language.Java.Spring`), also enable all parent namespaces that exist in the canonical list (e.g., `Language.Java`). The matching algorithm handles this automatically.

---

## Phase 0c Detection Algorithm

```
1. hawk op app tech-flags get --app <APP_NAME> --format json → CANONICAL_FLAGS{}
   If CANONICAL_FLAGS is empty, skip to step 5 with no flags to set.
2. Scan codebase for evidence files → DETECTED_TECHS[]
   (Check package.json, pom.xml, go.mod, requirements.txt, docker-compose.yml, Gemfile, *.csproj/*.sln)
3. Map DETECTED_TECHS to flag keys in CANONICAL_FLAGS → ENABLED_FLAGS[]
   (See heuristics and matching rules below)
4. If ENABLED_FLAGS is empty:
     Do NOT call disable-all or set
     Report: "No technology evidence found; tech flags unchanged."
     DONE
5. hawk op app tech-flags disable-all --app <APP_NAME> --yes
   (The --yes flag is required; agents must not use the interactive form without it)
6. hawk op app tech-flags set --app <APP_NAME> <KEY>=true ... (one entry per flag in ENABLED_FLAGS)
7. Report: which flags were enabled and what evidence triggered each
```

---

## Detection Heuristics

### Languages & Frameworks

| Evidence | Detection | Example Flag Key |
|----------|-----------|------------------|
| `package.json` present | JavaScript detected | `Language.JavaScript` |
| `package.json` contains `"react"` | React framework | `Language.JavaScript.React` |
| `package.json` contains `"next"` | Next.js framework | `Language.JavaScript.NextJs` |
| `package.json` contains `"vue"` | Vue.js framework | `Language.JavaScript.Vue` |
| `package.json` contains `"angular"` | Angular framework | `Language.JavaScript.Angular` |
| `package.json` contains `"express"` or `"fastify"` or `"koa"` | Node.js backend | `Language.JavaScript.Node` |
| `pom.xml` or `build.gradle` present | Java detected | `Language.Java` |
| `pom.xml` or `build.gradle` contains `spring-boot` or `spring-core` | Spring framework | `Language.Java.Spring` |
| `requirements.txt` or `pyproject.toml` present | Python detected | `Language.Python` |
| `requirements.txt` or `pyproject.toml` contains `django` | Django framework | `Language.Python.Django` |
| `requirements.txt` or `pyproject.toml` contains `flask` | Flask framework | `Language.Python.Flask` |
| `requirements.txt` or `pyproject.toml` contains `fastapi` | FastAPI framework | `Language.Python.FastAPI` |
| `go.mod` present | Go detected | `Language.Go` |
| `Gemfile` present | Ruby detected | `Language.Ruby` |
| `Gemfile` contains `rails` | Rails framework | `Language.Ruby.Rails` |
| `*.csproj` or `*.sln` present | .NET detected | `Language.Dotnet` |

### Databases

| Evidence | Detection | Example Flag Key |
|----------|-----------|------------------|
| `docker-compose.yml` contains `image: postgres:` | PostgreSQL detected | `Db.PostgreSQL` |
| `docker-compose.yml` contains `image: mysql:` or `image: mariadb:` | MySQL/MariaDB detected | `Db.MySQL` |
| `docker-compose.yml` contains `image: mongo:` | MongoDB detected | `Db.MongoDB` |
| `docker-compose.yml` contains `image: redis:` | Redis detected | `Db.Redis` |
| Connection string with `postgresql://` or `postgres://` | PostgreSQL URL found | `Db.PostgreSQL` |
| Connection string with `mysql://` | MySQL URL found | `Db.MySQL` |
| Connection string with `mongodb://` or `mongodb+srv://` | MongoDB URL found | `Db.MongoDB` |
| Connection string with `sqlserver://` or `mssql` | SQL Server detected | `Db.MicrosoftSqlServer` |

**How to find connection strings:** Search environment files (`.env`, `.env.local`, `.env.*.local`), config files (`config.yml`, `application.properties`, `appsettings.json`), Docker Compose services, and Kubernetes secrets/ConfigMaps.

---

## Matching Detected Techs to Canonical Flag Keys

The detection heuristics produce friendly tech names (e.g., "Spring", "PostgreSQL"). The `set` command requires exact canonical flag keys from the API.

**Primary rule: use explicit heuristic mappings first.** The detection heuristics table already maps specific evidence directly to expected canonical key names (e.g., "pom.xml or build.gradle → `Language.Java`"). Use those explicit mappings directly before falling back to terminal-segment fuzzy matching.

**Additionally:** If Phase 0a (repo linking) completed and returned `frameworkNames` from `hawk op repo list`, treat those as additional tech evidence — match each framework name against canonical flags using the terminal-segment rule below.

**Terminal-segment matching algorithm:**

The correct rule is **terminal segment matching**: a detected technology matches a canonical key only when the technology term matches the *last* (terminal) segment of the dot-namespaced key.

Example:
- Detected "Java" → matches `Language.Java` (terminal segment is "Java") ✓
- Detected "Java" → does NOT match `Language.Java.Spring` (terminal segment is "Spring") ✗
- Detected "Spring" → matches `Language.Java.Spring` ✓

Steps:

1. For each detected technology term:
   - Find canonical keys where the terminal segment (everything after the last `.`) matches the tech term (case-insensitive)
   - If multiple keys match (e.g., `Language.Java` and `Framework.Java`), prefer the one under the most relevant namespace
   - Add the matched key to ENABLED_FLAGS

2. For each key added to ENABLED_FLAGS, also add all parent namespace keys that exist in CANONICAL_FLAGS:
   - `Language.Java.Spring` is enabled → also add `Language.Java` if it exists
   - `Language.Java` is enabled → also add `Language` if it exists

3. Deduplicate ENABLED_FLAGS before calling `set`

4. **If no canonical key matches a detected tech, skip silently** and continue to the next detected tech.

---

## Example: Detect and Configure a Node.js + React + PostgreSQL App

**Step 1: Fetch canonical flags**
```bash
hawk op app tech-flags get --app myapp --format json
```

```json
{
  "Language.JavaScript": false,
  "Language.JavaScript.React": false,
  "Language.JavaScript.NextJs": false,
  "Language.JavaScript.Node": false,
  "Language.Python": false,
  "Language.Java": false,
  "Db.PostgreSQL": false,
  "Db.MySQL": false
}
```

**Step 2: Detect from codebase**
- `package.json` → JavaScript
- `package.json` contains `"react"` → React
- `package.json` contains `"express"` → Node
- `docker-compose.yml` contains `image: postgres:` → PostgreSQL

DETECTED_TECHS = ["JavaScript", "React", "Node", "PostgreSQL"]

**Step 3: Match to canonical keys**
- JavaScript → `Language.JavaScript` (explicit heuristic mapping)
- React → `Language.JavaScript.React` (terminal segment "React" matches)
- Node → `Language.JavaScript.Node` (terminal segment "Node" matches)
- PostgreSQL → `Db.PostgreSQL` (explicit heuristic mapping)

**Parent inclusion:**
- `Language.JavaScript.React` → also add `Language.JavaScript` (exists in canonical)
- `Language.JavaScript.Node` → `Language.JavaScript` already included
- `Db.PostgreSQL` has no parent namespace in canonical

ENABLED_FLAGS = [`Language.JavaScript`, `Language.JavaScript.React`, `Language.JavaScript.Node`, `Db.PostgreSQL`]

**Step 4: Disable all, then enable detected flags**
```bash
hawk op app tech-flags disable-all --app myapp --yes
```

```bash
hawk op app tech-flags set --app myapp \
  Language.JavaScript=true \
  Language.JavaScript.React=true \
  Language.JavaScript.Node=true \
  Db.PostgreSQL=true
```

**Step 5: Report**
```
Tech flags configured:
  - Language.JavaScript: enabled (detected package.json)
  - Language.JavaScript.React: enabled (detected react in package.json)
  - Language.JavaScript.Node: enabled (detected express in package.json)
  - Db.PostgreSQL: enabled (detected postgres: service in docker-compose.yml)
```

---

## No Match Policy

If codebase scanning finds **no evidence of any technology**, or all detected techs have no canonical key match:

1. **Do not call `disable-all`** — detection runs before the reset, so if no flags are found there is nothing to reset to
2. **Do not call `set`**
3. **Report:** "No technology evidence found; tech flags unchanged."

This preserves any manual flag configuration the user may have already set.

---

## Manual Override

Users can always manually enable additional flags after tech-flag auto-configuration:

```bash
hawk op app tech-flags set --app myapp Language.Java=true
```

This is safe and encouraged if:
- The agentic detection missed a technology (e.g., external service dependency not in codebase)
- The user wants to enable additional rule families for defense-in-depth
- A flag was disabled by mistake

---

## Troubleshooting

### `hawk op app tech-flags get` returns empty

No flags have been initialized yet. **Skip `disable-all` and proceed directly to detection.** After detection, call `set` to initialize the flags at the detected state.

### `hawk op app tech-flags disable-all` hangs

If `disable-all` hangs without the `--yes` flag, it is waiting for interactive confirmation — always use `--yes` in agentic contexts. If the hang persists even with `--yes`, skip the `disable-all` step and manually list all canonical keys in the `set` command instead (e.g., `set Language.JavaScript=false Language.JavaScript.React=false ...`).

### Detection found no techs

Expand heuristics:
- Check for additional config file types (e.g., `*.gradle.kts` for Gradle Kotlin, `Pipfile` for Python/Pipenv)
- Verify connection strings in all `.env*` files and config directories
- Look for `node_modules/`, `.gradle/`, `target/`, `venv/`, `__pycache__/` directories as fallback evidence
- Check inline code comments and imports (risky; use only as last resort)

### A detected tech has no matching canonical key

The tech exists in the codebase but the API does not have a flag for it. The detection algorithm silently skips it. Check the canonical list via `hawk op app tech-flags get` and report the gap if it's a widely-used framework.

### Flags were set but some not enabled

Possible causes:
- Flag name typo or case mismatch (flag names are case-sensitive)
- Flag does not exist in the canonical list for this StackHawk instance
- Value syntax error (use `true`/`false`, not `True`/`False`)
- Dry-run was used instead of actual `set` (try again without `--dry-run`)

Use `hawk op app tech-flags get` after `set` to verify the final state.
