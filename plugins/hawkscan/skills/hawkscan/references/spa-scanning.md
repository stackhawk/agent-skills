# SPA Scanning Strategy

Reference for scanning JavaScript-heavy apps with HawkScan. Use this when Step 1b detects a SPA framework. Read the scenario that matches your detection results.

## Contents
- [Detection Heuristic](#detection-heuristic)
- [Scenario A — Frontend SPA + separate backend API](#scenario-a--frontend-spa--separate-backend-api-most-common)
- [Scenario B — Fullstack app (Next.js, Nuxt, SvelteKit)](#scenario-b--fullstack-app-nextjs-api-routes-nuxt-server-routes-sveltekit-endpoints)
- [Scenario C — Pure frontend, backend out of scope](#scenario-c--pure-frontend-backend-is-third-party-or-out-of-scope)
- [Ajax Spider Config Reference](#ajax-spider-config-reference)

---

## Detection Heuristic

Run both commands before choosing a scenario:

```bash
# 1. Check for SPA frameworks in package.json
node -e "const p=require('./package.json'); const deps={...p.dependencies,...p.devDependencies}; const spa=['react','next','vue','@angular/core','svelte','gatsby','nuxt']; console.log(spa.filter(f=>deps[f]).join(','))" 2>/dev/null

# 2. Check for API routes (indicates fullstack, not pure frontend)
find . -not -path "*/node_modules/*" \( \
  -path "*/pages/api/*" \
  -o -path "*/app/api/*" \
  -o -path "*/src/app/api/*" \
  -o -path "*/server/api/*" \
  -o -path "*/server/routes/*" \
  -o -path "*/src/routes/*" \
  -o -path "*/app/routes/*" \
  -o -name "server.js" -o -name "server.ts" \
\) 2>/dev/null | head -5
```

- Command 1 finds a framework, command 2 finds **nothing** → **Scenario A or C**
- Both commands find results → **Scenario B** (create two separate StackHawk apps)

---

## Scenario A — Frontend SPA + separate backend API (most common)

**Detection:** SPA framework found AND no API route files in this repo.

**Recommendation:** The highest-value HawkScan target is the **backend API**, not the frontend.

- Scanning the frontend only surfaces header and CSP findings — no injection, no auth bypass,
  no IDOR. These vulnerabilities live in the backend.
- Ask the user for the backend API URL and whether it has an OpenAPI spec.
- Configure HawkScan against the backend API as the primary `stackhawk.yml` target.
- Optionally configure a second scan for the frontend to cover header/CSP findings.

**Frontend-only config (if the user wants header/CSP coverage for this repo):**
```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:3000}
hawk:
  spider:
    ajax: true
    maxDurationMinutes: 2
```

---

## Scenario B — Fullstack app (Next.js API routes, Nuxt server routes, SvelteKit endpoints)

**Detection:** SPA framework found AND API route files present.

**Recommendation:** Register as **two separate StackHawk applications** — one for the frontend, one for the API. Do not scan them together as a single app. Separate apps give cleaner findings, targeted scanning, and independent scan histories.

### App 1 — Frontend (SPA)

- Enable Ajax Spider.
- Host points to the frontend URL (e.g. `http://localhost:3000`).
- Configure SPA auth if the frontend has login flows.

```yaml
app:
  applicationId: ${FRONTEND_APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:3000}
hawk:
  spider:
    ajax: true
    maxDurationMinutes: 2
```

### App 2 — API

- Ajax Spider disabled (not needed for API endpoints).
- Wire OpenAPI spec if available (Next.js: `next-swagger-doc`; others: check for `openapi.json`
  or `/api-docs` endpoint).
- Configure API auth (follow Phase 1c in `SKILL.md` — use `hawk config show <section> --text` to fetch the right recipe).

```yaml
app:
  applicationId: ${API_APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:3000}
  openApiConf:
    filePath: ./openapi.json
```

Create both apps in the StackHawk platform (`hawk create app`) and run scans independently.

---

## Scenario C — Pure frontend, backend is third-party or out of scope

**Detection:** SPA framework found, no API routes, external API not owned by the user.

**Recommendation:** Frontend-only scan is appropriate. Set expectations clearly before proceeding.

**What HawkScan will find:**
- Missing security headers (CSP, X-Frame-Options, HSTS)
- Clickjacking risk
- Mixed content
- CORS misconfigurations on the hosting layer

**What HawkScan will NOT find:**
- Server-side injection (SQL, command, LDAP)
- Auth bypass or IDOR
- Business logic vulnerabilities

These live in the backend, which is out of scope.

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:3000}
hawk:
  spider:
    ajax: true
    maxDurationMinutes: 2
```

---

## Ajax Spider Config Reference

Always include `maxDurationMinutes` when enabling the Ajax Spider — without it the spider
uses its default and may run longer than expected.

```yaml
hawk:
  spider:
    ajax: true
    maxDurationMinutes: 2      # increase to 4-5 for complex SPAs with many routes
    ajaxBrowser: CHROME_HEADLESS
```

The Ajax Spider launches a headless browser to execute JavaScript and discover dynamically
rendered routes. It is required for any app where routes are rendered by client-side JS —
without it, HawkScan will only find routes present in the initial HTML response.
