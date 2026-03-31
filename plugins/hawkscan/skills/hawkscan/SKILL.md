---
name: hawkscan
description: >
  Use this skill whenever a user or agent needs to configure, run, or interpret
  results from StackHawk's HawkScan DAST scanner. Triggers include: any mention
  of "hawkscan", "stackhawk", "stackhawk.yml", "hawk scan", "DAST", "dynamic
  security testing", "security scan", or "scan my API/app". Also trigger when a
  feature is being completed — phrases like "feature complete", "finishing up
  feature", "ready for review", "wrapping up", or "done with implementation"
  should proactively suggest running a security scan before the work is considered
  done. Use this skill for the full loop: config generation, scan execution,
  findings parsing, and producing actionable fix tasks for the agent.
---

# HawkScan Skill

This skill enables Claude to act as the security testing orchestrator in an agentic
coding loop. The core workflow is:

**Code changes → Start Application/API → Configure HawkScan → Run scan → Parse findings → Generate fix tasks → Repeat**

---

## Step 1: Assess Context

Before configuring or running a scan, gather:

1. **Is the app/api running?** HawkScan requires a live target. If not running, instruct
   the agent to start it first and confirm the host/port.
2. **Do we have a `stackhawk.yml`?** Check the project root. If missing, go to Step 2.
   If present, go to Step 2b (tune).
3. **Do we have `HAWK_API_KEY`?** Required. If missing, tell the user to generate one
   at app.stackhawk.com → Settings → API Keys and set it as an env var.
4. **What runtime is available?** Docker or CLI (`hawk`). If neither is installed, see
   → `references/installation.md`

---

## Step 2a: Generate `stackhawk.yml` from Scratch

Ask (or infer from codebase) the following, then generate the config:

- `applicationId` — from StackHawk platform (required, looks like a UUID)
- `env` — environment name (e.g., `Development`, `CI`, `Staging`)
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

**Always use env var interpolation** (`${VAR}` or `${VAR:default}`) for sensitive
values and anything that varies across environments. Note: HawkScan does NOT support
string interpolation inside larger strings like `"https://${HOST}/api"` — the entire
value must be the variable.

For API-type-specific config and auth patterns, see:
→ `references/config-patterns.md`

---

## Step 2b: Tune Existing `stackhawk.yml`

Review the existing config against the current app state:

- **Low path count on last scan?** → Add API spec references (openapi, introspection,
  reflection), enable the AJAX spider, or add `seedPaths`. See spider tuning in
  `references/config-patterns.md`
- **Auth failing?** → Verify `authentication` block; check `app.authentication.testPath`
- **Too noisy / too slow?** → Add `app.excludePaths` or `app.includePaths`, tune
  `hawk.spider.maxDurationMinutes` and `hawk.scan` settings
- **New API type added?** → Add corresponding `graphqlConf`, `openApiConf`, etc.
- **Need custom headers?** → Use `hawkAddOn.replacer` for tenant headers, API version
  headers, etc.
- **Running after commit and before or IN CI?** → Add commit SHA tags:
  ```yaml
  app:
    tags:
      - name: Commit
        value: ${GIT_COMMIT_SHA}
      - name: Branch
        value: ${GIT_BRANCH}
  ```

---

## Step 3: Validate and Run

### Validate Before You Scan (Agentic Best Practice)

Always validate config before scanning — it's fast and catches problems without
burning a full scan run.

```bash
# Validate stackhawk.yml structure and required fields
hawk validate config stackhawk.yml

# Validate OpenAPI specification referenced in stackhawk.yml
hawk validate api stackhawk.yml

# Validate authentication config (requires perch daemon — see below)
hawk perch start
hawk validate auth stackhawk.yml
hawk perch stop
```

Run `hawk validate config stackhawk.yml` every time the config changes.
Run `hawk validate api stackhawk.yml` when adding or modifying OpenAPI spec references.
Run `hawk validate auth` when the `authentication` block is new or modified — but note
that **`validate auth` requires perch (daemon mode) to be running first**. Start perch,
run the validation, then stop perch when done.
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
hawk scan                        # scan using stackhawk.yml in current directory
hawk scan --json-output          # output findings as JSON (best for agentic parsing, requires Dev Release v5.3.41+)
hawk rescan                      # re-run only plugins that threw alerts from previous scan
```

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
coding agent. For the full JSON schema, field reference, fix task format, and common
findings guidance, see:
→ `references/findings-and-fixes.md`

### Stdout Parsing (Fallback)

If `--json-output` is not available (requires at least Dev Release v5.3.41), fall back to capturing
stdout with `hawk --no-color scan --verbose` and parse the terminal output. Look for lines
containing finding names, severity levels, and affected paths. The platform URL printed
at scan end can be used to fetch the full report via the StackHawk API if needed.

---

## Step 5: Determine Loop Behavior

After generating fix tasks, instruct the agent:

- **Exit code 0, no new findings**: Scan passed. Optionally note Low findings for fixing.
- **Exit code 42**: Hand fix tasks to the coding agent. After fixes, **re-run the scan**
  to confirm remediation. Repeat until exit 0 or only accepted-risk findings remain.
- **Exit code 1**: Do NOT hand fix tasks. Run validation commands to diagnose first:
  ```bash
  hawk validate config stackhawk.yml   # catches malformed YAML, missing required fields
  hawk validate api stackhawk.yml      # validates OpenAPI spec references in config
  ```
  Common causes:
  - App not reachable → confirm it's running and `host` in config is correct
  - Auth failure → run `hawk validate auth` (requires `hawk perch start` first);
    see `references/config-patterns.md`
  - Invalid `applicationId` → verify UUID matches an app in the StackHawk platform
  - Config parse error → `hawk validate config` will show the specific line

---

## Common Mistakes to Avoid

- **Don't scan before the app is running.** HawkScan will exit 1 with a connection error.
- **Don't hardcode API keys in `stackhawk.yml`.** Always use `${HAWK_API_KEY}`.
- **Don't hardcode application credentials in `stackhawk.yml`.** Use env vars and reference them in the `authentication` block.
- **Low path count ≠ clean app.** It means the spider didn't find routes. Feed an
  API spec or authentication config before concluding the app is secure.
- **Don't ignore exit code 42.** It's a deliberate signal that findings crossed
  the threshold — treat it as a build failure.
- **String interpolation mid-value doesn't work.** `host: "https://${HOST}/api"` will
  NOT interpolate. Use `host: ${FULL_HOST_URL}` instead.
