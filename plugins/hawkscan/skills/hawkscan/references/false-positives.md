# False Positives and Accepted Risk

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

```yaml
app:
  excludePaths:
    - /health
    - /actuator/info
    - /swagger-ui
    - /api-docs
```

### Set failure threshold to ignore Low-severity findings

```yaml
hawk:
  failureThreshold: MEDIUM
```

This means the scan still reports Low findings but exits with code `0` instead of
`42` — they won't trigger the fix loop.

### Exclude specific scan plugins

If a specific check consistently produces false positives for your stack:

```yaml
hawk:
  scan:
    excludePlugins:
      - 10096  # Timestamp Disclosure (common false positive on API timestamps)
```

Use this sparingly. Prefer path exclusions over disabling entire plugins.

## Reporting Accepted Risk

When you encounter a finding that is a known false positive or accepted risk:

1. **Do not "fix" intentional behavior.** Changing a deliberately open health endpoint
   to require auth will break monitoring.
2. **Add the path to `excludePaths`** in `stackhawk.yml` so it doesn't trigger again.
3. **Report it clearly:** "Finding X on path Y is an accepted risk because [reason].
   Added to excludePaths to prevent future false positives."
4. **If the StackHawk platform is available**, triage the finding as "Accepted Risk"
   with a note explaining why.

## When in Doubt

If you cannot determine whether a finding is a false positive:
- **Fix it.** A false negative (missing a real vulnerability) is far worse than
  spending time fixing a false positive.
- Flag it in your report: "Fixed [finding] — if this was intentional behavior,
  the change can be reverted and the path added to excludePaths."
