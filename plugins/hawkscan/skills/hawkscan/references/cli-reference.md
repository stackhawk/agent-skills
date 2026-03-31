# HawkScan CLI Reference

The `hawk` CLI is preferred for local/agentic use — lower overhead than Docker,
faster iteration on config, and better localhost networking.

**Option resolution order:** CLI flag → Environment Variable → `~/.hawk/hawk.properties`

---

## Top-Level Options

These go **before** the command (`hawk [options] <command>`):

```bash
hawk --api-key=${HAWK_API_KEY} scan      # supply API key inline (alternative to hawk init)
hawk --no-color scan                     # strip ANSI escape codes (required for log parsing)
hawk --num-stored-sessions=4 scan        # number of sessions to keep (default: 4)
hawk --log-roll-size=100MB scan          # log file roll size (default: 100MB)
hawk --log-files-count=10 scan           # max rolled log files to upload (default: 10)
```

---

## Setup

```bash
hawk init                                # first-time: prompts for API key, saves to ~/.hawk/hawk.properties
hawk --api-key=${HAWK_API_KEY} scan      # or supply key inline without init
```

---

## Core Scan Commands

```bash
hawk scan                                # scan using stackhawk.yml in current directory
hawk scan stackhawk-ci.yml              # scan with a specific config file
hawk scan base.yml override.yml         # merge configs (later file wins)
hawk rescan                              # re-run only plugins that threw alerts from previous scan
```

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
hawk validate auth stackhawk.yml         # validate auth config (requires perch running)
```

See the main SKILL.md Step 3 for config file path rules and common agent mistakes.

---

## Diagnostic Commands

```bash
hawk version                             # print CLI version
hawk list plugin                         # list available custom scan plugins
hawk download log                        # download the scan log from the last scan
hawk create app                          # create a new application in the StackHawk platform
```

---

## Perch (Daemon Mode)

Perch runs HawkScan as a background daemon. It is **required for `hawk validate auth`**
and also useful for recording traffic via a proxied browser.

```bash
hawk perch start                         # start background daemon
hawk perch status                        # check if daemon is running
hawk perch browser                       # launch Chrome proxied through HawkScan
hawk perch stop                          # stop daemon
```

Perch is NOT needed for standard `hawk scan` runs — but you must start it before
running `hawk validate auth`, then stop it afterward.

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
