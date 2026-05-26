# Failure Semantics Reference

How HawkScan signals scan outcomes in CI, when to block vs warn, and how to think about retries and caching.

## Exit Codes

| Exit code | Meaning | Pipeline action |
|---|---|---|
| `0` | Scan ran; no findings at or above `failureThreshold`. | Pass. |
| `1` | Scan failed before producing results (config error, app unreachable, auth failure, invalid `applicationId`, internal scanner error). | Fail. Do not retry — this is almost always a config issue that needs human attention. |
| `42` | Scan ran; findings met or exceeded `failureThreshold`. | **Real finding.** Either fail (block mode) or warn (warn-only mode), per the integration choice. |

Exit code 42 is the *intended success path of failure* — the scan worked, and it found something worth blocking on. Treating it like a flake (retrying, swallowing) defeats the purpose of running the scan.

## `failureThreshold` — Tuning the Block Line

`failureThreshold` in `stackhawk.yml` decides which severity levels trip exit code 42:

```yaml
app:
  applicationId: ${APP_ID}
  failureThreshold: High   # one of: High, Medium, Low, All
```

| Value | Exit 42 when... |
|---|---|
| `High` | Any **High** finding is present (default; recommended for new pipelines) |
| `Medium` | Any **Medium** or **High** finding is present |
| `Low` | Any **Low**, **Medium**, or **High** finding is present |
| `All` | Any finding at all is present (often noisy) |

**Tuning guidance:**
- Start at `High` for a new pipeline. You want the first month to be calibration — find out which severity levels your app actually produces, work through them, then ratchet down.
- Drop to `Medium` once the High-severity backlog is empty AND the team is committed to triaging Mediums within a sprint cadence.
- `Low` and `All` are appropriate only for high-maturity teams with active triage processes; otherwise the noise drowns out real signal.

The `hawkscan` skill owns `failureThreshold` writes — this skill does not change it. If the user asks to "make CI less noisy," route them to the `hawkscan` skill for the config edit (which also handles `excludePaths` and `excludePlugins`).

## Block-on-42 vs Warn-only

Three valid integration modes:

### Mode 1 — Block on 42 (default)

```yaml
# GitHub Actions
- uses: stackhawk/hawkscan-action@v2.5.0
  with:
    apiKey: ${{ secrets.HAWK_API_KEY }}
# (exit 42 naturally fails the step)
```

The exit code propagates; the job fails; the pipeline fails; the PR check turns red. **This is the right default** — it puts security findings on the same footing as test failures.

### Mode 2 — Warn-only

```yaml
- name: Run HawkScan (warn-only)
    # exit code handled explicitly below (do not use continue-on-error here)
  run: |
    set +e
    docker run --rm ... stackhawk/hawkscan:5.5.11
    EXIT_CODE=$?
    case $EXIT_CODE in
      0)  echo "HawkScan passed." ;;
      42) echo "::warning::HawkScan found findings — review at the platform URL above." ;;
      *)  echo "HawkScan errored (exit $EXIT_CODE) — failing the job." ; exit $EXIT_CODE ;;
    esac
```

Note: the wrapper still fails on exit code 1 (real errors). Only exit 42 is downgraded to a warning. **Never swallow exit 1** — that hides config breakage.

Use warn-only when:
- The pipeline is brand-new and you don't yet trust the threshold tuning.
- Findings are being worked through in parallel and you don't want every PR to block on them.
- The job is informational (e.g., on a `develop` branch where you accept noise).

Plan to graduate warn-only → block mode within a few weeks. Warn-only that never graduates is a security gap.

### Mode 3 — Scheduled-only baseline

Don't gate every PR; run a daily/weekly scheduled scan against the staging environment, and block deployment to production on its outcome (gate the release-promotion job, not the PR pipeline). Good fit for:
- Slow-to-bootstrap apps where per-PR scans add too much pipeline latency.
- Large monorepos where the relevant code surface is hard to scope per PR.
- Compliance scans that need a reliable cadence and traceability rather than per-commit coverage.

Example (GHA):

```yaml
name: HawkScan baseline
on:
  schedule: [{ cron: '0 6 * * *' }]   # daily at 06:00 UTC
  workflow_dispatch:
jobs:
  hawkscan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: stackhawk/hawkscan-action@v2.5.0
        env:
          APP_HOST: https://staging.example.com
        with:
          apiKey: ${{ secrets.HAWK_API_KEY }}
```

## Retry Strategy

**Don't auto-retry exit 42.** It's a finding, not a flake. Retrying masks the result and burns scan time.

**Retry exit 1 only on specific transient signals:**
- HTTP 5xx from the platform during scan submission (rare; the scanner handles its own retries internally).
- Container-pull failures (`Error response from daemon: ... timeout`).
- Network blips during initial app health-check.

Don't retry blindly. If retry succeeds, the original failure was a flake. If retry fails, the issue is real and needs investigation.

```yaml
# GitHub Actions retry pattern (exit 1 only, max 2 attempts)
- name: Run HawkScan (with retry on transient errors)
  run: |
    for attempt in 1 2; do
      docker run --rm ... stackhawk/hawkscan:5.5.11
      EXIT=$?
      case $EXIT in
        0|42) exit $EXIT ;;
        *)    echo "Attempt $attempt failed with exit $EXIT" ; sleep 10 ;;
      esac
    done
    exit $EXIT
```

## Caching Strategy

**Do cache:** the `hawk` CLI binary (when using Tier 3), the HawkScan Docker image layer (when the runner supports image caching).

**Do NOT cache:**
- Scan output / findings. Each scan must be independent — caching findings between runs defeats the purpose.
- `~/.hawk/` if `HAWK_API_KEY` is in the env (it's not in the cache anyway; just don't go out of your way to include it).

### GitHub Actions image cache

GHA's `ubuntu-latest` runners cache popular images automatically. For pinned non-latest tags, an explicit cache step is unusual — image pull is ~5 seconds on a warm cache.

### Caching the CLI download (Tier 3)

```yaml
- name: Cache hawk CLI
  uses: actions/cache@v4
  with:
    path: ~/hawk
    key: hawk-cli-5.5.11
- name: Install hawk if not cached
  run: |
    if [ ! -d ~/hawk ]; then
      curl -Lo /tmp/hawk.zip https://download.stackhawk.com/hawk/cli/hawk-5.5.11.zip
      unzip -d ~/ /tmp/hawk.zip
    fi
    echo "$HOME/hawk-5.5.11" >> $GITHUB_PATH
```

## Scheduled vs PR-Trigger Tradeoffs

| Dimension | PR-trigger | Scheduled |
|---|---|---|
| Coverage | Every change scanned | Whatever the staging env has at scan time |
| Latency | Adds N minutes to PR feedback | Zero PR impact |
| Spider efficacy | Lower (ephemeral env, fresh DB, limited test data) | Higher (staging has realistic data + auth state) |
| Triage cadence | Per-PR (small batches) | Per-day/week (potentially large batches) |
| False-positive rate | Higher (fresh envs miss auth, return early) | Lower (staging is realistically configured) |

**Common combination:** PR-trigger in warn-only mode for early signal, plus scheduled baseline in block-deploy mode for the real gate. The PR pipeline gives developers fast feedback; the scheduled scan is the source of truth.

## Common Mistakes

- **Retrying exit 42 as if it were a flake.** It isn't. Retry hides the result and inflates scan-minute spend.
- **Catching all non-zero exit codes and continuing.** Exit 1 means the scan didn't run — silently passing means CI claims a security check happened when none did.
- **Setting `failureThreshold: All` on day 1.** Drowns the team in noise; the first real finding gets buried. Start at `High`.
- **Using `continue-on-error: true` to ship warn-only.** That swallows exit 1 too. Use the explicit `case` pattern from Mode 2 instead.
- **Tying CI to `:latest` and being surprised when a hawk release changes default behavior.** Pin the version.
