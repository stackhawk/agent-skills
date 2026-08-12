# Findings Parsing and Fix Task Reference

## Contents
- [JSON Output Schema](#json-output-schema----json-output)
- [Agentic Fix Task Format](#agentic-fix-task-format)
- [Common Findings Quick Reference](#common-findings-quick-reference)

---

## JSON Output Schema (`--json-output`)

When running with `--json-output`, HawkScan produces a single pretty-printed JSON
object to stdout. All other output (progress bars, banners, status messages) is
suppressed.

**Important:** `--json-output` requires at least HawkScan Dev Release v5.3.41.

**Important:** `--json-output` cannot be used with `--trace` — the CLI will error
with exit code 1 if both are set.

### Full Schema

```json
{
  "scan": {
    "id": "uuid-or-null",
    "applicationId": "uuid",
    "environment": "Development",
    "host": "https://example.com",
    "status": "COMPLETED",
    "duration": 45,
    "platformUrl": "https://app.stackhawk.com/scans/uuid"
  },
  "findings": [
    {
      "name": "Cross-Site Scripting",
      "severity": "HIGH",
      "count": 3,
      "cweId": "CWE-79",
      "paths": [
        {
          "path": "/api/users",
          "method": "GET",
          "status": "NEW"
        }
      ]
    }
  ],
  "errors": [
    {
      "message": "Authentication failed",
      "category": "AUTH"
    }
  ],
  "warnings": [
    "CDN headers detected: [x-cdn-header]"
  ],
  "thresholdResult": "PASS"
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `scan.id` | string or null | Scan UUID. Null if scan never started (pre-HSTE error) |
| `scan.applicationId` | string | Application UUID from config |
| `scan.environment` | string | Environment name (e.g., "Development") |
| `scan.host` | string | Target URL being scanned |
| `scan.status` | string | `COMPLETED`, `ERROR`, or `UNKNOWN` |
| `scan.duration` | int or null | Scan duration in seconds. Null if scan never started |
| `scan.platformUrl` | string or null | Link to scan results on StackHawk platform |
| `findings[]` | array | List of detected vulnerabilities. Empty `[]` if clean |
| `findings[].name` | string | Alert name (e.g., "SQL Injection") |
| `findings[].severity` | string | `HIGH`, `MEDIUM`, or `LOW` |
| `findings[].count` | int | Number of instances found across all paths |
| `findings[].cweId` | string | CWE identifier (e.g., "CWE-89") |
| `findings[].paths[]` | array | Affected endpoints |
| `findings[].paths[].path` | string | Endpoint path (e.g., "/api/users") |
| `findings[].paths[].method` | string | HTTP method (`GET`, `POST`, etc.) |
| `findings[].paths[].status` | string | Triage status: `NEW`, `FALSE_POSITIVE`, `RISK_ACCEPTED`, or `ASSIGNED` |
| `errors[]` | array | Errors during scan. Empty `[]` if none |
| `errors[].message` | string | Error description |
| `errors[].category` | string | Error category: `AUTH`, `CONFIG`, `UNKNOWN`, etc. |
| `warnings[]` | array of strings | Preflight/runtime warnings. Empty `[]` if none |
| `thresholdResult` | string | `PASS`, `FAIL`, or `UNKNOWN` |

### Relationship to Exit Codes

| `thresholdResult` | Exit Code | Meaning |
|--------------------|-----------|---------|
| `PASS` | `0` | No findings at or above `failureThreshold` |
| `FAIL` | `42` | Findings met or exceeded `failureThreshold` |
| `UNKNOWN` | `1` | Scan errored before threshold could be evaluated |

---

## Agentic Fix Task Format

Transform parsed findings into structured fix tasks for the coding agent:

```json
{
  "scan_summary": {
    "exit_code": 42,
    "high": 2,
    "medium": 5,
    "low": 3,
    "platform_url": "https://app.stackhawk.com/scans/..."
  },
  "fix_tasks": [
    {
      "priority": 1,
      "severity": "High",
      "vulnerability": "SQL Injection",
      "cwe": "CWE-89",
      "affected_paths": ["POST /api/users/search", "GET /api/products"],
      "description": "Unsanitized user input is being interpolated directly into SQL queries.",
      "fix_guidance": "Use parameterized queries or a prepared statement ORM. Never concatenate user input into SQL strings.",
      "evidence_summary": "Attack payload `' OR 1=1--` in `q` parameter returned 200 with expanded result set.",
      "reproduce_curl": "curl -X POST http://localhost:8080/api/users/search -d '{\"q\": \"\\' OR 1=1--\"}'"
    }
  ]
}
```

### Priority Rules

1. **High severity first** — always
2. Within same severity, **order by exploitability**: injection > auth bypass > IDOR > XSS > header issues
3. **Group by root cause** when multiple paths share the same vulnerability — one fix likely covers all
4. Low severity items can be batched as a single "security hygiene" task

---

## Common Findings Quick Reference

| Finding | Likely Cause | Fix Direction |
|---------|-------------|---------------|
| SQL Injection | String-concatenated queries | Parameterized queries / ORM |
| XSS (Reflected) | Unescaped user input in response | Output encoding; CSP header |
| Missing Security Headers | No middleware config | Add helmet.js / security header middleware |
| IDOR | No ownership check on resource | Verify `user_id` matches authenticated principal |
| Path Traversal | Unvalidated file path input | Allowlist paths; strip `../` sequences |
| Broken Auth | Session/token misconfig | Review token validation, expiry, scope |
| Information Disclosure | Verbose error messages | Sanitize error responses in production |
