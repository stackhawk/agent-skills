# False Positives and Accepted Risk

## Contents
- [Identifying False Positives](#identifying-false-positives)
- [How to Decide: Fix or Suppress?](#how-to-decide-fix-or-suppress)
- [Suppression via Config](#suppression-via-config)
- [Triaging via the API](#triaging-via-the-api)
- [Reporting Accepted Risk](#reporting-accepted-risk)
- [When in Doubt](#when-in-doubt)

---

## Identifying False Positives

Not every finding from a DAST scan is a real vulnerability. Some common false positive
scenarios:

- **Health check or status endpoints** that intentionally return server info (e.g.,
  `/health`, `/actuator/info`) may trigger "Information Disclosure" findings
- **CORS headers** set intentionally permissive for public APIs
- **Deliberately open endpoints** (public API docs, login pages) flagged for missing
  authentication
- **Security headers on non-HTML responses** — CSP, X-Frame-Options findings on JSON
  API endpoints that never serve HTML
- **Rate limiting findings** on endpoints that are already behind an API gateway
  enforcing rate limits

## How to Decide: Fix or Suppress?

| Signal | Action |
|--------|--------|
| The finding describes real user-input handling with no sanitization | **Fix it** |
| The finding is on a test/mock endpoint not present in production | **Suppress** — exclude the path |
| The finding is on an intentionally open endpoint (health, docs) | **Suppress** — exclude the path |
| The finding is a header issue on a non-HTML API response | **Suppress** — exclude the path or accept the risk |
| You're unsure | **Fix it** — false negatives are worse than false positives |

## Suppression via Config

### Exclude specific paths from scanning

The scanner is pinned to the `host:` value in `stackhawk.yml` and will not
traverse to other hosts. You do **not** need to add external domains or CDN
URLs to `excludePaths` — the scanner won't follow them.

Use `excludePaths` for same-host paths that generate noise without security
value: static assets (images, CSS, JavaScript bundles), health endpoints,
API docs, and similar paths that are either not user-controllable or not
relevant to security testing.

```yaml
app:
  excludePaths:
    - /health
    - /actuator/info
    - /swagger-ui
    - /api-docs
    - /static
    - /assets
```

### Control which severity triggers exit code 42

`failureThreshold` belongs under `hawk:` — **never under `app:`**.

```yaml
hawk:
  failureThreshold: MEDIUM   # LOW | MEDIUM | HIGH
```

The scan always reports all findings regardless of this setting. `failureThreshold`
only controls the exit code: the scan exits `42` (triggering the fix loop) when a
finding at or above the threshold is found; otherwise it exits `0`.

Use this to gate CI pipelines by severity — for example, allow Low findings to pass
without triggering the fix loop while still recording them in the platform.

### Exclude specific scan plugins

If a specific check consistently produces false positives for your stack:

```yaml
hawk:
  scan:
    excludePlugins:
      - 10096  # Timestamp Disclosure (common false positive on API timestamps)
```

Use this sparingly. Prefer path exclusions over disabling entire plugins.

## Triaging via the API

Use `hawk op scan triage` to record false-positive decisions on the platform.
This is the preferred action over config suppression when the finding is a true
false positive — it creates an auditable, human-reviewable record.

### When to use API triage vs. config suppression

| Scenario | Action |
|----------|--------|
| Scanner is definitively wrong about this endpoint | **API triage** → `false-positive` with note |
| Finding is real but uncertain — needs more review | **API triage** → `add-comment` with context |
| Finding is noisy but not clearly wrong | **Fix it** — when in doubt, fix |

### Single finding

```bash
hawk op scan triage \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --status false-positive \
  --note "<reason — explain specifically why the scanner is wrong>"
```

Example notes:
- `"CSP finding on JSON endpoint /api/health which never serves HTML; header inapplicable"`
- `"CORS wildcard on public read-only metrics API; no auth, no sensitive data"`
- `"Rate-limit finding on /api/events; rate limiting enforced at API gateway layer"`

### Bulk (multiple findings in one scan)

Write a `triage.yaml`:
```yaml
- finding_hash: "sha256hash1"
  status: FALSE_POSITIVE
  note: "Health endpoint — intentional server info exposure for monitoring"
- finding_hash: "sha256hash2"
  status: FALSE_POSITIVE
  note: "CORS permissive by design; public read-only API"
```

Then apply:
```bash
hawk op scan triage --scan <SCAN_UUID> --from-file triage.yaml
```

JSON format is also accepted (leading `[` is auto-detected). Max 100 actions per call — split into batches if needed.

### Agent rules for API triage

- ✅ Mark `FALSE_POSITIVE` autonomously — note must explain clearly why
- ✅ Use `ADD_COMMENT` to annotate without changing status
- ❌ **Never mark `RISK_ACCEPTED`** — human decision only
- ❌ **Never mark `ASSIGNED`** — human decision only
- ❌ Never suppress a finding by changing code to hide it from the scanner

```bash
# ADD_COMMENT example — for findings under review but not yet confirmed FP
hawk op scan triage \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --status add-comment \
  --note "Reviewing with team; suspected false positive on /actuator/info"
```

> **Permission-independent alternative:** `hawk op finding note` adds the same kind
> of annotation through an ungated route (`POST .../findings/triage/notes`), so it
> works even without `WRITE_TRIAGE`. Prefer it for comment-only annotations when the
> account may lack triage permission. See
> [When triage is denied](#when-triage-is-denied-no-write_triage).

### When triage is denied (no `WRITE_TRIAGE`)

`hawk op scan triage` writes through the permission-gated
`POST .../findings/triage` endpoint. If the account lacks `WRITE_TRIAGE` — either by
role default, or because the org enabled the `LIMITED_MEMBER_ROLE` setting that turns
off member finding-triage (it revokes `WRITE_TRIAGE` from the MEMBER role) — the
command fails with an unauthorized-feature error (a 401 after a valid login).

Detection is **reactive**: attempt `hawk op scan triage`; if it returns the
unauthorized-feature error, fall back to `hawk op finding note`, which writes through
the ungated `POST .../findings/triage/notes` route (any org member, no
`WRITE_TRIAGE`). The note route ignores status, so it can only annotate.

**Intent was `ADD_COMMENT`** — re-issue as a note; the result is identical, so
annotation never fails for lack of permission:

```bash
hawk op finding note \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --note "Reviewing with team; suspected false positive on /actuator/info [triaged by ${HAWK_AGENT:-agent}]"
```

**Intent was `FALSE_POSITIVE`** — the status cannot change without `WRITE_TRIAGE`.
Record the reasoning as a note (audit trail preserved), prefixed so a reviewer knows
the status action is still pending, then escalate to the user:

```bash
hawk op finding note \
  --scan <SCAN_UUID> \
  --hash <FINDING_HASH> \
  --note "[Agent-proposed FALSE_POSITIVE — apply status in UI; WRITE_TRIAGE required] CSP finding on JSON endpoint /api/health which never serves HTML; inapplicable [triaged by ${HAWK_AGENT:-agent}]"
```

Then tell the user, for example:

> Recorded my false-positive reasoning as a note on finding `<hash>`, but changing
> its status needs `WRITE_TRIAGE`, which this account lacks (possibly due to the
> org's limited-member setting). A workspace admin can apply FALSE_POSITIVE in the
> platform UI.

Bulk notes use the same `--from-file` form (max 100 per call); each entry needs only
`finding_hash` and `note` (no `status`):

```bash
hawk op finding note --scan <SCAN_UUID> --from-file notes.yaml
```

### How to get the finding hash

The finding hash (`--hash`) comes from the scan JSON output:
```bash
hawk scan --json-output | jq '.findings[].hash'
```

Or from `hawk op scan get`:
```bash
hawk op scan get --app <APP_NAME> --detail full --format json | jq '.data.findings[].hash'
```

The scan UUID (`--scan`) comes from:
```bash
hawk scan --json-output | jq -r '.scan.id'
```

## Reporting Accepted Risk

When you encounter a finding that is a known false positive:

1. **Do not "fix" intentional behavior.** Changing a deliberately open health endpoint
   to require auth will break monitoring.
2. **Triage via the API** using `hawk op scan triage` (see section above) so the decision
   is recorded and auditable.
3. **Report it clearly:** "Finding X on path Y is a false positive because [reason].
   Marked via API triage with note: [note]."

## When in Doubt

If you cannot determine whether a finding is a false positive:
- **Fix it.** A false negative (missing a real vulnerability) is far worse than
  spending time fixing a false positive.
- Flag it in your report: "Fixed [finding] — if this was intentional behavior,
  the change can be reverted and the path added to excludePaths."
