# High-Iteration Findings Reference

Findings that commonly cause agents to loop. For each, "done" is defined — use the
verify command before rescanning, and escalate at the threshold instead of continuing.

## Contents
- [Content Security Policy (CSP)](#content-security-policy-csp)
- [CORS (Cross-Origin Resource Sharing)](#cors-cross-origin-resource-sharing)
- [Authentication / Broken Auth (Unprotected Endpoint)](#authentication--broken-auth-unprotected-endpoint)
- [Missing Security Headers](#missing-security-headers-hsts-x-frame-options-x-content-type-options-referrer-policy)

---

**Escalation thresholds:**
- **2 rescans** for complex policy/config findings: CSP, CORS, Auth
- **1 rescan** for simple additive fixes: Missing Security Headers

**Iteration-limit note:** Guard Rails says "max one fix-rescan cycle per task" — that
applies to the autonomous loop as a whole. The escalation thresholds below apply within
a single fix attempt for a specific finding. After escalating, report the finding rather
than restarting the full loop.

---

## Content Security Policy (CSP)

**Why it fires:** Missing `Content-Security-Policy` header, or header present but uses
`unsafe-inline`, `unsafe-eval`, or wildcard (`*`) sources.

**Minimal done fix:**
- HTML-serving routes: Add a CSP header eliminating wildcards and `unsafe-*` directives.
  Starter policy: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'`
- JSON/API endpoints that never serve HTML: Mark as false positive — CSP is inapplicable
  to non-HTML responses. Use the `hawk op scan triage` command from Step 5.

**Verify before rescanning:**
```bash
curl -sI <url> | grep -i content-security-policy
```
If this returns empty, the header isn't being sent — check middleware order and route scope
before rescanning. Do not rescan until the header appears here.

**Rescan expectation:** 0 CSP findings for the fixed paths.

**Escalate when:** The header appears in `curl -sI` output but the scanner still fires after
**2 rescans**. Stop iterating; surface the specific directive the scanner objects to and ask
the user.

---

## CORS (Cross-Origin Resource Sharing)

**Why it fires:** `Access-Control-Allow-Origin: *` on endpoints that serve authenticated or
sensitive responses.

**Minimal done fix:** Restrict `Allow-Origin` to known origins; remove the wildcard for any
credentialed or authenticated endpoint.

**False positive condition (narrow):** Only mark as false positive if the endpoint (a) requires
no authentication AND (b) explicitly serves public reference data (health checks, public API
docs, public config). If the response contains any user-derived or session-derived data, route
to the fix loop — do not mark as FP.

**Verify before rescanning:**
```bash
curl -sI -H "Origin: https://example.com" <url> | grep -i access-control
```
Confirm `Access-Control-Allow-Origin` is set to a specific origin, not `*`.

**Rescan expectation:** Findings clear for the restricted origins.

**Escalate when:** Origins are restricted and confirmed in the curl output, but findings persist
after **2 rescans**. Surface the specific origin/path pair and ask the user.

---

## Authentication / Broken Auth (Unprotected Endpoint)

**Scope:** This entry covers findings where an endpoint is missing authentication enforcement.
If the finding involves session management, token validation, CSRF, or token scope — not a
missing auth decorator — **escalate immediately without iterating**. Those require human review
of the auth architecture.

**Why it fires:** A protected endpoint is reachable without valid credentials.

**Minimal done fix:** Verify `[Authorize]` / `@PreAuthorize` / `@Secured` / equivalent is
applied to the flagged endpoint AND that auth middleware is registered in the correct order.
Do not add workarounds — identify and protect the specific unprotected endpoint.

**Verify before rescanning:**
```bash
curl -sI <url>
```
Should return `401` or `403` without credentials. If it returns `200`, the fix hasn't taken
effect yet — check middleware registration order before rescanning.

**Rescan expectation:** Auth findings clear once the endpoint correctly enforces authentication.
If findings shift to different paths, the middleware scope is wrong — review route ordering.

**Escalate when:** The endpoint returns `401`/`403` in curl without credentials but the scanner
still bypasses auth after **2 rescans**. Stop; surface the specific bypass request and ask the
user.

---

## Missing Security Headers (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)

**Why it fires:** Response missing one or more of: `Strict-Transport-Security`,
`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`.

**Minimal done fix:** Add all four via a security header middleware in one change:
- Node.js: `app.use(helmet())`
- .NET: Add `app.UseHsts()`, `app.UseXContentTypeOptions()`, `app.UseXfo(...)`, `app.UseReferrerPolicy(...)`
- Java Spring: Configure `http.headers()` in `SecurityConfig`
- Other: Set headers manually in a response filter/interceptor

One middleware addition should close all four findings at once.

**Verify before rescanning:**
```bash
curl -sI <url> | grep -iE "strict-transport|x-frame|x-content-type|referrer-policy"
```
All four should appear. If any are missing, the middleware has route exclusions or isn't
registered — fix before rescanning.

**Rescan expectation:** All header findings clear in one rescan.

**Escalate when:** All four headers appear in `curl -sI` output but the scanner still flags
after **1 rescan**. (These are binary — header present or not. If verification passes and the
scanner still fires, there's an environment-level issue the agent can't resolve by iterating.)
Surface the specific header + path and ask the user.
