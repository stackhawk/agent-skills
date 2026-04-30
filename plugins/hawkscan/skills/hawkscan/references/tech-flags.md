# Tech Flags Reference

Auto-detect your application's technology stack and configure StackHawk tech flags accordingly.

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
hawkop app tech-flags get --app <APP_NAME> --format json
```

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
hawkop app tech-flags disable-all --app <APP_NAME> --yes
```

Flips all flags to `false` in one operation. The `--yes` flag is **required** in non-interactive contexts (scripts, agents); omit it for interactive use (will prompt for confirmation).

**Important:** If the API returns an empty flag list (no flags defined yet), skip this step and proceed directly to detection.

### Enable detected flags

```bash
hawkop app tech-flags set --app <APP_NAME> \
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
hawkop app tech-flags set --app <APP_NAME> \
  Language.Java=true \
  Language.Java.Spring=true \
  --dry-run
```

Shows what would change without applying the update.

---

## Flag Name Rules

- **Dot-namespaced:** `Language.Java`, `Language.Java.Spring`, `Db.PostgreSQL`
- **Case-sensitive:** `Language.Java` ≠ `language.java`
- **API is source of truth:** Always validate flag names via `hawkop app tech-flags get` before using them in `set` commands
- **Parent namespace inclusion:** When enabling a child flag (e.g., `Language.Java.Spring`), also enable all parent namespaces that exist in the canonical list (e.g., `Language.Java`). The matching algorithm handles this automatically.

---

## Phase 0c Detection Algorithm

```
1. Call: hawkop app tech-flags get --app <APP_NAME> --format json
   → Store result as CANONICAL_FLAGS (a dict of all valid flag keys and current states)
   → If CANONICAL_FLAGS is empty, skip step 2 and proceed to step 3

2. If CANONICAL_FLAGS is not empty:
   Call: hawkop app tech-flags disable-all --app <APP_NAME> --yes
   → Reset all flags to false

3. Scan codebase for evidence (files, config, dependencies)
   → Produce DETECTED_TECHS[] (list of technology identifiers: "Java", "Spring", "PostgreSQL", etc.)

4. For each tech in DETECTED_TECHS:
   a. Find all canonical keys matching the tech (case-insensitive substring match on each dot-separated segment)
   b. From matches, select the most specific (deepest namespace wins)
   c. If the selected flag has a parent namespace that exists in CANONICAL_FLAGS, also include parent in enabled list
   d. If no canonical key matches, skip silently

5. If any flags were selected in step 4:
   Call: hawkop app tech-flags set --app <APP_NAME> <KEY1>=true <KEY2>=true ...
   → Enable only the detected flags

6. If no flags were detected in step 3 or no matches in step 4:
   → Do not call set; leave flags at current state
   → Report: "No technology evidence found; tech flags unchanged."

7. Report results: list which flags were enabled and what codebase evidence triggered each
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

The detection heuristics produce friendly tech names (e.g., "Spring Boot", "PostgreSQL"). The `set` command requires exact canonical flag keys from the API.

**Matching algorithm:**

1. **Perform substring match (case-insensitive)** on each dot-separated segment of the canonical key.
   - Detected tech "Spring" matches canonical keys containing "spring" (case-insensitive): `Language.Java.Spring`, `Framework.Spring`
   - Detected tech "PostgreSQL" matches: `Db.PostgreSQL`, `Database.PostgreSQL`

2. **From all matches, select the most specific** (deepest namespace wins).
   - Detected "Spring" with matches `[Language.Java.Spring, Framework.Spring]`: choose `Language.Java.Spring` (deeper)
   - Detected "Java" with matches `[Language.Java, Language.Java.Spring]`: choose `Language.Java.Spring` if both are in canonical; if only `Language.Java` exists, choose that

3. **When enabling a child flag, also enable parents** that exist in CANONICAL_FLAGS.
   - If enabling `Language.Java.Spring`, also check if `Language.Java` exists in CANONICAL_FLAGS and enable it too
   - If a parent does not exist in CANONICAL_FLAGS, do not try to enable it

4. **If no canonical key matches a detected tech, skip silently** and continue to the next detected tech.

---

## Example: Detect and Configure a Node.js + React + PostgreSQL App

**Step 1: Fetch canonical flags**
```bash
hawkop app tech-flags get --app myapp --format json
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

**Step 2: Disable all**
```bash
hawkop app tech-flags disable-all --app myapp --yes
```

**Step 3: Detect from codebase**
- `package.json` → JavaScript
- `package.json` contains `"react"` → React
- `package.json` contains `"express"` → Node
- `docker-compose.yml` contains `image: postgres:` → PostgreSQL

DETECTED_TECHS = ["JavaScript", "React", "Node", "PostgreSQL"]

**Step 4: Match to canonical keys**
- JavaScript → `Language.JavaScript`
- React → `Language.JavaScript.React` (more specific than `Language.JavaScript`)
- Node → `Language.JavaScript.Node` (more specific)
- PostgreSQL → `Db.PostgreSQL`

**Parent inclusion:**
- `Language.JavaScript.React` has parent `Language.JavaScript` (exists in canonical) → include both
- `Language.JavaScript.Node` has parent `Language.JavaScript` (already included)
- `Db.PostgreSQL` has no parent namespace

**Flags to enable:** `Language.JavaScript=true`, `Language.JavaScript.React=true`, `Language.JavaScript.Node=true`, `Db.PostgreSQL=true`

**Step 5: Enable flags**
```bash
hawkop app tech-flags set --app myapp \
  Language.JavaScript=true \
  Language.JavaScript.React=true \
  Language.JavaScript.Node=true \
  Db.PostgreSQL=true
```

**Step 6: Report**
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

1. **Do not call `disable-all`** (or call it, then proceed without calling `set`)
2. **Do not call `set`**
3. **Report:** "No technology evidence found; tech flags unchanged."

This preserves any manual flag configuration the user may have already set.

---

## Manual Override

Users can always manually enable additional flags after tech-flag auto-configuration:

```bash
hawkop app tech-flags set --app myapp Language.Java=true
```

This is safe and encouraged if:
- The agentic detection missed a technology (e.g., external service dependency not in codebase)
- The user wants to enable additional rule families for defense-in-depth
- A flag was disabled by mistake

---

## Troubleshooting

### `hawkop app tech-flags get` returns empty

No flags have been initialized yet. **Skip `disable-all` and proceed directly to detection.** After detection, call `set` to initialize the flags at the detected state.

### `hawkop app tech-flags disable-all` hangs

This is a known issue in `hawk` CLI 5.4.0. Upgrade to 5.5.0+, or skip the `disable-all` step and manually list all canonical keys in the `set` command (e.g., `set Language.JavaScript=false Language.JavaScript.React=false ...`).

### Detection found no techs

Expand heuristics:
- Check for additional config file types (e.g., `*.gradle.kts` for Gradle Kotlin, `Pipfile` for Python/Pipenv)
- Verify connection strings in all `.env*` files and config directories
- Look for `node_modules/`, `.gradle/`, `target/`, `venv/`, `__pycache__/` directories as fallback evidence
- Check inline code comments and imports (risky; use only as last resort)

### A detected tech has no matching canonical key

The tech exists in the codebase but the API does not have a flag for it. The detection algorithm silently skips it. Check the canonical list via `hawkop app tech-flags get` and report the gap if it's a widely-used framework.

### Flags were set but some not enabled

Possible causes:
- Flag name typo or case mismatch (flag names are case-sensitive)
- Flag does not exist in the canonical list for this StackHawk instance
- Value syntax error (use `true`/`false`, not `True`/`False`)
- Dry-run was used instead of actual `set` (try again without `--dry-run`)

Use `hawkop app tech-flags get` after `set` to verify the final state.
