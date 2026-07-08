---
name: optimize
version: 2.3.0
description: >
  Analyze a codebase and produce an optimal HawkScan setup — tech flags, scan-policy
  plugin selection, and stackhawk.yml corrections — then apply it as a non-destructive
  trial, run ONE trial scan, and promote or discard. Use when the user asks to
  "optimize my scan", "tune HawkScan", "make my scan faster", "reduce false positives",
  "pick the right plugins/policy for my app", or invokes /optimize. Also invoked
  automatically by the hawkscan skill once at onboarding to set up the scan policy +
  tech flags (Setup mode), and re-runnable anytime via /optimize; the metrics Refine
  mode is surfaced when a scan is slow. Do NOT use for: a normal security scan or
  fixing vulnerabilities (use the hawkscan skill); querying existing findings or
  posture (use the api skill); or editing stackhawk.yml without optimizing/scanning.
  Requires an onboarded StackHawk app + env and a `hawk` build whose `hawk op` has the
  `policy` write commands.
---

# Optimize Skill

Turn a codebase into an optimal HawkScan configuration. The skill detects the real tech
stack and app shape, expresses that as a **trial scan policy** (tech flags + plugins) plus
local `stackhawk.yml` corrections, runs one trial scan so the user sees real results, and
then promotes the setup or discards it with no residue.

## Why a trial policy (not editing the app)

Org scan policies are stored as hosted assets and downloaded by the scanner at scan time
when `app.scanPolicy.name` is set (see `references/trial-lifecycle.md`). Creating a trial
policy and referencing it in `stackhawk.yml` therefore leaves the application's own policy,
plugins, and tech flags **untouched** until the user promotes. This is the core safety
property.

## Preflight (run before anything else)

```bash
# Identify the driving skill for CLI usage telemetry (read by hawk/hawkop).
export _STACKHAWK_SKILL=optimize
```

1. **CLI versions / auth** — reuse the hawkscan skill's preflight (`hawk version`,
   `hawk config --help`, `hawk op` auth). Additionally confirm the policy write commands
   exist: `hawk op policy create --help` must succeed. If it errors with "unrecognized
   subcommand", STOP and tell the user to upgrade hawk.
   Also confirm metrics support: `hawk op scan metrics --help` must succeed. If it errors
   with "unrecognized subcommand", the metrics/refine phase is skipped (pre-scan
   optimization still works); tell the user to upgrade hawk to enable refinement.
2. **App + env** — resolve the target app and env. If the app is not onboarded, defer to
   the hawkscan skill's onboarding, then return here.
3. **Permissions / feature flag** — the org needs `ORG_POLICY_MANAGEMENT` + `WRITE_POLICY`
   /`DELETE_POLICY`. If a `policy create` dry-run reports a permission/feature error,
   degrade to **recommend-only**: print the proposed policy JSON + yml diff and stop.

## Workflow

Two modes. **Setup** configures scan policy + tech flags (no scan) and is what hawkscan
onboarding invokes; it is also re-runnable anytime via `/optimize`. **Refine** runs a trial
scan and tunes from per-path metrics; it runs only via `/optimize` or when a scan is slow.

0. **Preflight** (above).

### Setup (config) — tech flags + scan policy, no trial scan

1. **Analyze codebase** — detect languages/frameworks/DBs and app shape
   (REST vs SPA, GraphQL, OpenAPI spec, base paths, auth). See `references/mapping.md`.
2. **Compute optimal config** — tech flags to enable, plugin include/exclude set, and
   `stackhawk.yml` corrections. Default to a **balanced** profile; honor an explicit
   speed↔coverage lean if the user gives one. See `references/mapping.md`.
3. **Build the policy** — fetch a base preset (`hawk op policy get --name DEFAULT`
   or the API/GraphQL preset matching the app), edit its tech flags + toggle plugin
   families, write the result to a temp JSON file, and create it under a deterministic
   name matching `^[A-Z0-9_]+$` (e.g. `OPTIMIZE_TRIAL_<APP>_<ENV>`, upper-snake, sanitized).
   See `references/cli-contract.md` and `references/trial-lifecycle.md`.
4. **Reference it locally** — back up `stackhawk.yml`, then set
   `app.scanPolicy: { name: OPTIMIZE_TRIAL_… }` plus app-type/OpenAPI/auth corrections.
   Show the diff; never clobber unrelated keys. **Setup ends here** — the named policy is
   referenced in `stackhawk.yml` (the scanner downloads it by name); promotion to the app
   default is a Refine concern, not required here.

### Refine (metrics) — trial scan + per-path tuning

5. **Trial scan** — run one `hawk scan`. The scanner downloads the policy and applies
   its tech flags + plugins. **Capture the trial scan id**, findings, and duration.
6. **Analyze scan metrics** — run `hawk op scan metrics <SCAN_ID> --format json` and parse
   the per-path/operation metrics, signal flags, and request health. See
   `references/metrics-and-refine.md`. If no metrics are available, skip to step 8.
7. **Surface + refine (tiered loop)** — present scan health + top paths + a recommendations
   block (per active flag: affected paths, proposed lever, tier, expected effect). Then:
   - **auto-apply** concurrency reductions for `rate-limited` / `timeout-prone`
     (`hawk.scan.concurrentRequests` — halve from its current yml value, default 20, floor 1);
   - **propose** coverage-reducing or input-needing levers (`app.excludePaths` for
     `heavy-path`/`slow-path`; `app.authentication.*` for `auth-wall`) with the exact yml
     diff, applying only approved changes.
   If any change was applied, **re-scan** and return to step 6 with the new scan id.
   STOP when no new high-severity flags remain, after **3** refine iterations, or when the
   user declines further refinement. All edits go to the trial `stackhawk.yml` (backed up).
   See `references/metrics-and-refine.md` for the full mapping + loop control.
8. **Present & decide** — show the final results and an exact diff (tech-flag changes,
   plugin set, yml edits incl. any `excludePaths`/`concurrentRequests`), then ask:
   **promote** or **discard**.
9. **Promote / discard** — see `references/trial-lifecycle.md`. Promote: re-create the
   policy under a permanent name, point `stackhawk.yml` at it (keeping the refined
   scope/concurrency yml edits), delete the trial policy, leave the yml change for the user
   to commit. Discard: `hawk op policy delete` the trial policy and restore the
   `stackhawk.yml` backup.

## Safety rules

- Never mutate the app's own tech flags/plugins; all optimization lives in the trial policy.
- Always `--dry-run` a `policy create`/`delete` first when validating preflight.
- On ANY failure after trial-policy creation, delete the trial policy and restore the
  `stackhawk.yml` backup before reporting the error.
- Trial-policy names are deterministic so a re-run can detect and clean up an orphan from a
  crashed previous run (delete a stale `OPTIMIZE_TRIAL_…` before creating a fresh one).
- Refine edits (`concurrentRequests`, `excludePaths`) go to the trial `stackhawk.yml` only;
  discard reverts them with the backup. Never auto-apply path exclusions or auth changes —
  those require explicit confirmation.
- Cap refinement at 3 iterations; floor `hawk.scan.concurrentRequests` at 1 (never 0).

## Companion skills

- `hawkscan` — runs the actual scan loop and owns the onboarding flow + the fallback
  tech-flag detection heuristics (`references/tech-flags.md`), used only when this skill
  can't create a scan policy.
- `api` — read-only platform lookups via `hawk op` (app/env/policy listing).
