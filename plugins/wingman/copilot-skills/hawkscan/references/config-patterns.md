# HawkScan Config Patterns Reference

> **Looking for per-field syntax?** Use `hawk config show <field-path> --text` for the canonical reference (e.g. `hawk config show hawk.spider --text`). This file documents *patterns* — env var interpolation, multi-env composition, common config-time gotchas — not individual field reference.

For authentication, follow Phase 1c in `SKILL.md` (uses `hawk config show <section> --text`).

## Table of Contents
1. [Env Var Interpolation](#env-var-interpolation)
2. [Multi-Environment Config](#multi-environment-config)
3. [Common Config-Time Gotchas](#common-config-time-gotchas)

---

## Env Var Interpolation

**Always use env var interpolation** (`${VAR:default}`) for sensitive values and anything that varies across environments.

**Syntax:** HawkScan uses `${VAR:default}` — single colon, no dash. The bash form `${VAR:-default}` is NOT supported.

**Whole-value rule:** The entire YAML value must be the variable. Mid-string interpolation does NOT work:

```yaml
# WRONG — will NOT interpolate
host: "https://${HOST}/api"

# RIGHT — interpolate the entire value
host: ${FULL_HOST_URL}
```

If you need a composed value, compose it in the shell first and export a single env var:

```bash
export FULL_HOST_URL="https://${HOST}/api"
hawk scan
```

---

## Multi-Environment Config

### Preferred: Host interpolation (one file, works everywhere)

Use `${VAR:default}` interpolation for host-only differences. **Never** create a second YAML file just to change the host.

```yaml
# stackhawk.yml — one file, works everywhere
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:https://your-default-host.com}
```

Override the host at runtime without touching the file:
```bash
# Scan locally
APP_HOST=http://localhost:3000 hawk scan

# Scan staging
APP_HOST=https://staging.example.com hawk scan
```

### Multi-file layering (for structurally different scan settings)

Use file layering only when environments need meaningfully different settings — different `env` name, different `failureThreshold`, or CI-only tags. **Not** for host-only differences.

**`stackhawk.yml`** (base — shared settings):
```yaml
app:
  applicationId: ${APP_ID}
  openApiConf:
    filePath: openapi.yaml
```

**`stackhawk-ci.yml`** (CI override — structurally different settings):
```yaml
app:
  env: CI
  host: http://localhost:8080
tags:
  - name: _STACKHAWK_GIT_COMMIT_SHA
    value: ${COMMIT_SHA:none}
  - name: _STACKHAWK_GIT_BRANCH
    value: ${BRANCH_NAME:none}
hawk:
  failureThreshold: high
```

Run with both files — later file takes precedence:
```bash
hawk scan stackhawk.yml stackhawk-ci.yml
```

For the syntax of any individual field above (e.g. `tags`, `hawk.failureThreshold`, `app.openApiConf`), use:
```bash
hawk config show <field-path> --text
```

---

## Common Config-Time Gotchas

- **Never create a separate `stackhawk.local.yml`** just to change the host. Use `${APP_HOST:...}` interpolation in the primary `stackhawk.yml`. If a `stackhawk.local.yml` already exists for host overrides, delete it and migrate to interpolation.

- **`${VAR:-default}` (bash form) silently fails.** HawkScan uses `${VAR:default}` (no dash). A config file written with `:-` will not interpolate, and the default will not apply.

- **Mid-string interpolation does NOT work.** `host: "https://${HOST}/api"` is a literal string. Always make the entire YAML value the variable: `host: ${FULL_HOST_URL}`.

- **Don't hardcode credentials in `stackhawk.yml`.** Use env vars and reference them. `${HAWK_API_KEY}` for the platform key, app credentials via the `authentication` block (see Phase 1c in `SKILL.md`).

- **Tags live at the top level**, not under `app:`:
  ```yaml
  app:
    applicationId: ${APP_ID}
  tags:                                # ← top-level, NOT under app:
    - name: _STACKHAWK_GIT_COMMIT_SHA
      value: ${COMMIT_SHA:none}
  ```

- **Try `https://` first — HawkScan accepts self-signed certificates.** If an app runs on HTTPS, set `host: https://localhost:<port>` and let the scanner attempt the connection. Only fall back to `http://` or investigate TLS configuration if the scan actually fails to connect with an SSL/TLS error.

- **Validate after every change.** Run `hawk validate config stackhawk.yml` after any edit. Cheap; catches syntax and schema errors before a wasted scan run.
