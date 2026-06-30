# HawkScan CLI Reference

The `hawk` CLI is preferred for local/agentic use — lower overhead than Docker,
faster iteration on config, and better localhost networking.

**Option resolution order:** CLI flag → `API_KEY` environment variable → `~/.hawk/hawk.properties`. For local/agentic use, run `hawk init --browser` to write credentials to `~/.hawk/hawk.properties` — no env var needed. For CI/CD pipelines, prefix invocations with `API_KEY=$HAWK_API_KEY hawk ...`.

## Contents
- [Top-Level Options](#top-level-options)
- [Setup](#setup)
- [Core Scan Commands](#core-scan-commands)
- [Scan Flags for Agentic Loops](#scan-flags-for-agentic-loops)
- [Validation Commands](#validation-commands)
- [hawk config](#hawk-config)
- [Diagnostic Commands](#diagnostic-commands)
- [Perch (Daemon Mode)](#perch-daemon-mode)
- [Subcommand Options](#subcommand-options)
- [Exit Codes](#exit-codes)
- [Config File Path Rules](#config-file-path-rules)

---

## Top-Level Options

These go **before** the command (`hawk [options] <command>`):

```bash
hawk scan                                # after `hawk init --browser` — credentials from ~/.hawk/hawk.properties
hawk --no-color scan                     # strip ANSI escape codes (required for log parsing)
hawk --num-stored-sessions=4 scan        # number of sessions to keep (default: 4)
hawk --log-roll-size=100MB scan          # log file roll size (default: 100MB)
hawk --log-files-count=10 scan           # max rolled log files to upload (default: 10)
```

---

## Setup

```bash
hawk init --browser                      # first-time: browser device-flow auth, saves to ~/.hawk/hawk.properties
API_KEY=$HAWK_API_KEY hawk scan          # CI/CD: pass key directly when no local config (pipelines, Docker)
```

---

## Core Scan Commands

```bash
hawk scan                                          # scan using stackhawk.yml in current directory
hawk scan stackhawk-ci.yml                         # scan with a specific config file
hawk scan base.yml override.yml                    # merge configs (later file wins)
hawk rescan                                        # re-run plugins that fired on the most recent scan
hawk rescan --scan-id <SCAN_ID>                    # re-run plugins against a specific prior scan
hawk rescan --scan-id <SCAN_ID> --json-output      # rescan + structured output for parsing
```

### Rescan: fast fix verification

`hawk rescan` re-runs only the plugins that produced findings on the
parent scan, skipping the rest of the test suite. This turns the scanner
into a targeted regression-test engine, ideal for the agentic fix loop:

1. Run an initial `hawk scan --json-output` — capture `scan.id` from the
   JSON output.
2. Hand findings to a coding agent, let it fix them.
3. Run `hawk rescan --scan-id <that scan.id> --json-output` to verify
   fixes — dramatically faster than a full re-scan (often seconds vs.
   minutes).

**Triage and tags inherit from the parent scan.** A finding that was
`Accepted` on the parent will still be `Accepted` on the rescan.
Tags (commit SHA, branch) should be re-set before rescan if the commit
changed due to fixes — re-export `COMMIT_SHA` / `BRANCH_NAME` and update
the top-level `tags:` block in `stackhawk.yml` before running
`hawk rescan`. See SKILL.md Step 2b for the tag syntax.

**When to use a full `hawk scan` instead of rescan:**
- Fixes added new API endpoints, input vectors, or auth paths (rescan
  won't test them).
- The codebase has changed substantially since the parent scan.
- You want to baseline a new release where the full policy needs to
  pass, not just the subset that fired previously.

---

## Scan Flags for Agentic Loops

These go **after** `scan` (`hawk scan [options]`):

```bash
hawk scan --json-output                  # output findings as JSON to stdout (best for agentic parsing)
hawk scan --verbose                      # stream log output to stdout (useful for capturing progress)
hawk scan --debug                        # enable debug logging (use when diagnosing failures)
hawk scan --trace                        # trace-level HTTP logging (auth debugging)
hawk scan --hawk-mem=2g                  # increase JVM memory for large apps (default: 9g)
```

**For agentic use, prefer `--json-output`** for structured findings parsing. When you
need human-readable log output instead, use `hawk --no-color scan --verbose`.

**Note:** `--json-output` and `--trace` cannot be used together — the CLI will error
with exit code 1 if both are set.

**Note:** `--json-output` requires at least HawkScan Dev Release v5.3.41. If not
available in your version, fall back to `hawk --no-color scan --verbose` and parse stdout.

---

## Validation Commands

```bash
hawk validate config stackhawk.yml       # validate YAML structure and required fields
hawk validate api stackhawk.yml          # validate OpenAPI spec references
hawk validate auth stackhawk.yml         # validate auth config (live login test)
```

See the main SKILL.md Step 3 for config file path rules and common agent mistakes.

---

## `hawk config`

**Requires hawk v6.0.0 or newer.** Older hawk versions don't have the `config` subcommand. The skill's Prerequisites section enforces this with a preflight check; this section just documents the surface.

Look up HawkScan configuration reference and recipes. Reads the canonical knowledge artifact bundled with hawk (shared with the hosted-scanner auth-analyzer flow).

```bash
# Show docs for one section (JSON by default; --text for raw markdown)
hawk config show <path> [--text]

# Enumerate available sections (JSON array; --prefix to filter; --text for newline-separated)
hawk config list [--prefix <path>] [--text]

# Alias for `show` on curated recipe paths
hawk config recipe <path> [--text]
```

**Examples:**

```bash
hawk config show app.authentication.oauth --text
hawk config list --prefix app.authentication --text
hawk config show hawk.spider --text
```

This skill calls `hawk config show <section> --text` during Phase 1c to fetch auth recipes from the canonical source instead of carrying duplicates.

---

## Diagnostic Commands

```bash
hawk version                             # print CLI version
hawk list plugin                         # list available custom scan plugins
hawk download log                        # download the scan log from the last scan
# Interactive (human use - prompts for name)
hawk create app

# Non-interactive (agent/script use - required for autonomous operation)
hawk create app --name "My App" --env Development
```

**Important for agents:** Always use the non-interactive form. The interactive prompt
blocks execution and cannot be answered programmatically.

---

## Perch (Daemon Mode)

Perch runs HawkScan as a background daemon. It is useful for recording traffic via a
proxied browser. (`hawk validate auth` manages its own daemon lifecycle — you do not
need to start perch separately for auth validation.)

```bash
hawk perch start                         # start background daemon
hawk perch status                        # check if daemon is running
hawk perch browser                       # launch Chrome proxied through HawkScan
hawk perch stop                          # stop daemon
```

`hawk validate auth` also supports `--watch` to continuously re-test auth as you
modify the config:
```bash
hawk validate auth stackhawk.yml --watch
```

---

## Subcommand Options

These flags are available on `scan`, `validate`, and `perch` subcommands. They go
**after** the subcommand (`hawk scan [options]`):

### Scan Scope & Environment

```bash
hawk scan --repo-dir=<path>              # set base directory for config files
hawk scan -e VAR=value                   # override env vars in YAML config
hawk scan --env-file=.env                # load env vars from file
hawk scan --application-id=<uuid>        # override applicationId from config
hawk scan --environment-name=<name>      # override environment from config
```

### Scanner Behavior

```bash
hawk scan --session-home=<path>          # custom working directory (default: ~/.hawk/sessions)
hawk scan --no-progress                  # suppress terminal progress bars
hawk scan --hawk-mem=<size>              # max memory allocation (default: 9g)
hawk scan --proxy-port=<int>             # start scanner proxy on specific port
hawk scan --enable-preflight             # enable preflight checks
hawk scan --disable-preflight            # disable preflight checks
hawk scan --log-http                     # log HTTP request/responses
hawk scan --hawk-jvm-opts=<opts>         # pass JVM options to the scanner
```

### Output & Artifacts

```bash
hawk scan --sarif-artifact               # save results in SARIF format (stackhawk.sarif)
hawk scan --json-output                  # output findings as JSON to stdout
```

### Git Integration

```bash
hawk scan --git-url=<url>                # clone a git repo before scanning
hawk scan --git-rev=<rev>                # checkout specific revision/branch (with --git-url)
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | Scan complete, no findings at or above `failureThreshold` |
| `1`  | Scan failed (config error, app unreachable, auth failure) |
| `42` | Scan complete, findings met or exceeded `failureThreshold` |

---

## Config File Path Rules

The validate and scan commands accept config files as **positional arguments only** — there is
NO `-c` or `--config` flag. Do NOT invent one.

```bash
# CORRECT — positional args, just the filename
hawk validate config stackhawk.yml
hawk validate config stackhawk.yml stackhawk-override.yml
hawk validate auth stackhawk.yml
hawk scan stackhawk.yml

# WRONG — there is no -c flag
hawk validate config -c stackhawk.yml        # ← WILL FAIL
hawk validate auth --config stackhawk.yml    # ← WILL FAIL
```

The CLI automatically prepends the working directory to config file paths:
- **Use bare filenames** (e.g., `stackhawk.yml`) when the file is in the current directory
- **Do NOT pass absolute paths** like `/Users/me/project/stackhawk.yml` — the CLI prepends
  `projectRepoDir/` to it, producing a broken double-path
- To scan from a different directory, use `--repo-dir=<path>` to set the base directory,
  then pass just the filename

This applies to `hawk scan`, `hawk validate config`, `hawk validate api`, and `hawk validate auth`.
