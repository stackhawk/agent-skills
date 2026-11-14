# Scan Metrics → Refine Loop

After the trial scan, analyze its metrics and refine the config using real scan data.
This skill does NOT compute metrics — it consumes `hawk op scan metrics`.

## Get the metrics

```
hawk op scan metrics <SCAN_ID> --format json
```

`<SCAN_ID>` is the trial scan's id (use the id returned by the trial scan; `latest` also works).
Output (`MetricsJson`):

```json
{
  "scan_id": "...",
  "request_health": { "timeout": 0, "connection_failure": 0, "timeout_streak_max": 0 },
  "scan_flags": ["timeout-prone"],
  "paths": [
    {
      "method": "GET", "path": "/x", "total_requests": 100,
      "status_counts": {"200": 90, "429": 10},
      "class_2xx": 90, "class_3xx": 0, "class_4xx": 10, "class_5xx": 0,
      "error_rate": 0.10,
      "time": {"p50_bucket": 256, "p90_bucket": 4096, "max_bucket": 8192, "est_total_ms": 30000},
      "flags": ["slow-path", "rate-limited"]
    }
  ],
  "operations": []
}
```

Useful read-only views (human framing): `--sort {heaviest|slowest|erroring|most-requested}`,
`--top N`, `--method <VERB>`, `--operations`.

## Flag → lever mapping

| Flag | Meaning | Lever | Tier | Goal |
|------|---------|-------|------|------|
| `rate-limited` | 429s from target | lower `hawk.scan.concurrentRequests` | auto | better+faster |
| `timeout-prone` | target overwhelmed/flaky (scan-level) | lower `hawk.scan.concurrentRequests` | auto | reliability |
| `heavy-path` | path dominates est. scan time | `app.excludePaths` (or narrow `includePaths`) | confirm | faster |
| `slow-path` | high p90 latency | `app.excludePaths` if low security value | confirm | faster |
| `auth-wall` | >=50% 401/403 — route not actually tested | guide `app.authentication.*` (never fabricate creds) | confirm / needs-input | better coverage |
| `server-erroring` / `error-prone` | app erroring under scan | surface for investigation; optionally `app.excludePaths` | advisory / confirm | better findings |

## Tiers

- **auto** = concurrency reductions ONLY (non-destructive, reversible, no coverage loss).
  Apply, then re-scan.
- **confirm** = anything that drops coverage (`app.excludePaths`) or needs human input
  (`app.authentication.*`). Show the exact yml diff; apply only on explicit approval.

## Concurrency step-down

First read the CURRENT `hawk.scan.concurrentRequests` from `stackhawk.yml` (default 20 if
unset). On `rate-limited` or `timeout-prone`, step down by halving from that current value
(e.g. 20→10→5, or a user's custom 8→4→2), floor at 1 (never 0). NEVER raise it above the
user's configured value. After each re-scan, re-check whether the 429/timeout flags
cleared; stop lowering once they do.

## Exclusion guidance

- Report estimated time saved using the path's `est_total_ms` (and its share of the summed
  per-path `est_total_ms` across `paths[]`).
- `app.excludePaths` / `app.includePaths` are global path-pattern lists (no per-path
  strength knob exists). Exclusion = coverage loss → always confirm.

## Loop control

1. Run `scan metrics` on the just-finished trial scan.
2. Surface health + top paths + a recommendations block (per flag: affected paths, lever,
   tier, expected effect).
3. Apply auto-tier changes; for confirm-tier, present the diff and apply only approved ones.
4. If any change was applied, re-scan and go to step 1 with the new scan id.
5. STOP when: no new high-severity flags, OR 3 refine iterations reached, OR the user
   declines further refinement. Then proceed to promote/discard.

## Where changes persist on promote

- `stackhawk.yml` carries scope/pressure levers (`app.excludePaths`, `app.includePaths`,
  `hawk.scan.concurrentRequests`) and auth.
- The named scan policy carries tech flags + plugins (unchanged by this phase).
- Discard reverts the `stackhawk.yml` backup AND deletes the trial policy (base optimize rule).

## No metrics?

If `scan metrics` reports no path metrics (empty `paths[]` and `operations[]`), skip the refine loop and
proceed to promote/discard with a note. This is not an error.
