# SPA Scanning Strategy

Reference for scanning JavaScript-heavy apps with HawkScan. Use this when Step 1a determines the app is a SPA. Pick the scenario that matches the app.

## Contents
- [Choosing a scenario](#choosing-a-scenario)
- [Scenario A — Frontend SPA + separate backend API](#scenario-a--frontend-spa--separate-backend-api-most-common)
- [Scenario B — Fullstack app (Next.js, Nuxt, SvelteKit)](#scenario-b--fullstack-app-nextjs-api-routes-nuxt-server-routes-sveltekit-endpoints)
- [Scenario C — Pure frontend, backend out of scope](#scenario-c--pure-frontend-backend-is-third-party-or-out-of-scope)
- [Ajax Spider Config Reference](#ajax-spider-config-reference)

---

## Choosing a scenario

You already established whether the app is a SPA while understanding it (Step 1a in
SKILL.md). Pick the scenario by whether a backend API also lives in **this** repo:

- SPA, and no backend API in this repo → **Scenario A or C** (frontend and backend are
  separate; the backend is usually the higher-value target).
- SPA **and** a backend API in this repo (Next.js API routes, Nuxt/SvelteKit server
  routes, an embedded `server.*`) → **Scenario B** (register two separate StackHawk apps).

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
