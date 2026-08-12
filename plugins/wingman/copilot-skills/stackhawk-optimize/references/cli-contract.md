# hawk op CLI Contract (commands this skill calls)

| Purpose | Command |
|---------|---------|
| List policies (find base preset names) | `hawk op policy list --format json` |
| Fetch a base policy as JSON | `hawk op policy get --name <PRESET>` |
| Create/upsert a trial or permanent policy | `hawk op policy create --file <json> --name <NAME> [--display-name <DN>] [--dry-run]` |
| Delete a policy | `hawk op policy delete --name <NAME> --yes [--dry-run]` |
| (Optional) set app default | `hawk op policy assign --app <NAME\|UUID> --name <NAME> [--dry-run]` |
| Read canonical tech flags | `hawk op app tech-flags get --app <APP> --format json` |
| Get per-path scan metrics + signal flags | `hawk op scan metrics <SCAN_ID\|latest> [--sort heaviest\|slowest\|erroring\|most-requested] [--top N] [--method <VERB>] [--operations] --format json` |

Notes:
- `policy get` prints a full `ScanPolicy` JSON (tech flags + plugins) suitable for editing
  and re-submitting via `policy create --file`.
- Policy names must match `^[A-Z0-9_]+$`, ≤256 chars.
- All write commands support `--dry-run`; use it in preflight to detect missing
  permissions/feature flags without making changes.
- `scan metrics --format json` returns `MetricsJson` (paths[] with metrics + flags,
  operations[], request_health, scan_flags). The skill consumes this in the post-scan
  refine loop (see `metrics-and-refine.md`); it does not recompute metrics.
