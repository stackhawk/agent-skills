# HawkScan CLI Reference

The `hawk` CLI is preferred for local/agentic use — lower overhead than Docker,
faster iteration on config, and better localhost networking.

**Option resolution order:** CLI flag → Environment Variable → `~/.hawk/hawk.properties`

## Setup

```bash
hawk init                        # first-time: prompts for API key, saves to ~/.hawk/hawk.properties
hawk --api-key=${HAWK_API_KEY} scan  # or supply key inline without init
```

## Core Scan Commands

```bash
hawk scan                        # scan using stackhawk.yml in current directory
hawk scan stackhawk-ci.yml       # scan with a specific config file
hawk scan base.yml override.yml  # merge configs (later file wins)
hawk rescan                      # re-run only plugins that threw alerts from previous scan
```

## Useful Flags for Agentic Loops

```bash
hawk --json-output scan          # output findings as JSON to stdout (best for agentic parsing)
hawk --verbose scan              # stream log output to stdout (useful for capturing progress)
hawk --debug scan                # enable debug logging (use when diagnosing failures)
hawk --trace scan                # trace-level HTTP logging (auth debugging)
hawk --no-color scan             # strip ANSI escape codes (required for log parsing)
hawk --hawk-mem=2g scan          # increase JVM memory for large apps (default is low)
```

**For agentic use, prefer `--json-output`** for structured findings parsing. When you
need human-readable log output instead, use `--no-color --verbose`.

**Note:** `--json-output` and `--trace` cannot be used together — the CLI will error
with exit code 1 if both are set.

## Validation Commands

```bash
hawk validate config stackhawk.yml   # validate YAML structure and required fields
hawk validate api stackhawk.yml      # validate OpenAPI spec references
hawk validate auth stackhawk.yml     # validate auth config (requires perch running)
```

See the main SKILL.md Step 3 for config file path rules and common agent mistakes.

## Diagnostic Commands

```bash
hawk version                     # print CLI version
hawk list plugin                 # list available custom scan plugins
hawk download log                # download the scan log from the last scan
hawk create app                  # create a new application in the StackHawk platform
```

## Perch (Daemon Mode)

Perch runs HawkScan as a background daemon. It is **required for `hawk validate auth`**
and also useful for recording traffic via a proxied browser.

```bash
hawk perch start                 # start background daemon
hawk perch status                # check if daemon is running
hawk perch browser               # launch Chrome proxied through HawkScan
hawk perch stop                  # stop daemon
```

Perch is NOT needed for standard `hawk scan` runs — but you must start it before
running `hawk validate auth`, then stop it afterward.

## Additional Flags

These flags are available on scan, validate, and init commands:

```bash
hawk --session-home=<path> scan      # custom working directory (default: ~/.hawk/sessions)
hawk --no-progress scan              # suppress terminal progress bars
hawk --sarif-artifact scan           # save results in SARIF format (stackhawk.sarif)
hawk --proxy-port=<int> scan         # start scanner proxy on specific port
hawk --enable-preflight scan         # enable preflight checks
hawk --disable-preflight scan        # disable preflight checks
hawk --log-http scan                 # log HTTP request/responses
hawk --application-id=<uuid> scan    # override applicationId from config
hawk --environment-name=<name> scan  # override environment from config
hawk --repo-dir=<path> scan          # set base directory for config files
hawk -e VAR=value scan               # override env vars in YAML config
hawk --env-file=.env scan            # load env vars from file
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | Scan complete, no findings at or above `failureThreshold` |
| `1`  | Scan failed (config error, app unreachable, auth failure) |
| `42` | Scan complete, findings met or exceeded `failureThreshold` |
