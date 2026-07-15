# OpenAPI Spec Accuracy Reference

A REST scan is only as good as the spec behind it. An **accurate** spec is one whose
operations match the app's real routes *and* resolve against the scanned host — same base
path, same context path. An inaccurate spec is worse than no spec: HawkScan faithfully
requests every path it declares, so wrong paths become a wall of 404s that bury real
coverage and generate recurring false-positive noise on every rescan.

This reference is framework-generic. Use it whenever a REST surface needs a spec wired into
`openApiConf` — discovery (SKILL.md Step 1a / `scan-planning.md`) points here, and the
quality gate points here when it reports a `spec-not-wired` or coverage gap.

## Contents
- [The one rule: an unverified spec is a hypothesis](#the-one-rule-an-unverified-spec-is-a-hypothesis)
- [Get an accurate spec (preference order)](#get-an-accurate-spec-preference-order)
- [Framework spec-generation matrix](#framework-spec-generation-matrix)
- [Suggesting the code/build change](#suggesting-the-codebuild-change)
- [Base path and context path](#base-path-and-context-path)
- [Mandatory: verify the spec resolves](#mandatory-verify-the-spec-resolves)
- [Deriving a spec by hand (no tooling)](#deriving-a-spec-by-hand-no-tooling)

---

## The one rule: an unverified spec is a hypothesis

A checked-in `openapi.yaml`, a spec you generated, and a spec the app serves are all
*claims* about the API until you prove they resolve against the running app. Never wire a
spec into `openApiConf` and scan without the verification in "Mandatory: verify the spec
resolves" below. A checked-in file is the least trustworthy source — it drifts from the code,
can be stale, hand-maintained, or (as seen in the wild) emptied by a commit — so treat its
presence as a starting hypothesis, not a done task.

## Get an accurate spec (preference order)

Prefer a spec the framework produces from the *running app* over any static artifact. Work
down this list; stop at the first that yields a spec that passes verification.

1. **The running app already serves one.** Probe the common served endpoints once the app is
   up (see the matrix for framework-specific paths):
   ```bash
   for p in /openapi.json /openapi.yaml /v3/api-docs /v3/api-docs.yaml \
            /swagger.json /swagger/v1/swagger.json /api-docs /q/openapi; do
     curl -sf -o /dev/null -w "%{http_code} $p\n" "$APP_BASE_URL$p"
   done
   ```
   A 200 here is the best source — it reflects real routing, including base/context path.
   Wire it live with `openApiConf.path: <that path>` so the scan always reads the current
   spec.
2. **The framework can generate/serve one with a small change, but it isn't enabled.** This is
   the ideal outcome — see "Suggesting the code/build change". Add the tooling, rebuild,
   then fetch as in step 1.
3. **Only a static spec is checked in.** Verify it's current (path count matches the route
   grep from discovery; paths resolve — see verification). If it's stale, prefer regenerating
   via step 1/2. If you must use it, wire `openApiConf.filePath: <file>` and verify.
4. **A spec is published *outside* the repo.** Mature projects often maintain an accurate spec
   somewhere other than the app repo — check before giving up: a docs site (e.g.
   `api-docs.<project>.org`, a ReDoc/Swagger-UI page), a dedicated `<project>/api-docs` or
   `<project>-openapi` repo, a spec published as a release asset or package, or a link in the
   README/docs. This is exactly Firefly III's situation — no spec in-repo, but a complete one
   at `firefly-iii/api-docs`. Fetch it, pin the version to match the app, wire `filePath`, and
   verify it resolves (an external spec can lag the running app).
5. **No spec anywhere and no tooling for this stack.** Derive one by hand from the route
   inventory — see "Deriving a spec by hand".

## Framework spec-generation matrix

Examples, not an exhaustive list. The method generalizes: identify the framework from the
manifest, then determine its idiomatic OAS support. For anything not listed, **find out** —
`hawk config show`/docs won't help here, so search "`<framework>` openapi generation" or
check the framework's own docs before concluding none exists.

| Stack | Idiomatic OAS tooling | Serves at | Notes |
|-------|----------------------|-----------|-------|
| FastAPI (Python) | built in | `/openapi.json` | Already served — no change needed; just probe. |
| NestJS (Node) | `@nestjs/swagger` | `/api-json` (configurable) | First-party. |
| Express / Fastify (Node) | `swagger-jsdoc` + `swagger-ui-express`; `@fastify/swagger` | configurable | JSDoc-annotation or plugin based. |
| Spring Boot (Java/Kotlin) | `springdoc-openapi-starter-webmvc-ui` | `/v3/api-docs` | Reflects `server.servlet.context-path` in its server URL. |
| Quarkus (Java) | `quarkus-smallrye-openapi` | `/q/openapi` | Often on by default in dev. |
| Django REST Framework | `drf-spectacular` | `/api/schema/` | `drf-yasg` is the older alternative. |
| Flask (Python) | `apiflask`, `flasgger`, `flask-smorest` | configurable | — |
| ASP.NET Core | `Swashbuckle.AspNetCore` or `NSwag` | `/swagger/v1/swagger.json` | Often scaffolded already. |
| Go | `swaggo/swag`, `danielgtaylor/huma` | configurable | swag generates from annotations. |
| Rails | `rswag` | configurable | Spec-from-request-specs. |
| Laravel (PHP) | `l5-swagger`, `scramble` | configurable | Scramble infers without annotations. |
| Rust | `utoipa`, `aide` | configurable | — |

## Suggesting the code/build change

When the framework can emit an accurate spec but doesn't yet (preference step 2), this is the
highest-value move: a served, framework-generated spec is accurate by construction and stays
current as the code changes. Explore and suggest a **concrete** change — not "consider adding
OpenAPI support":

- Name the exact dependency and where it goes (the build file + coordinate/version).
- Show the minimal config/annotation to expose the endpoint, and state the served path.
- State the DAST value it unlocks ("wires N routes HawkScan otherwise can't see; replaces a
  stale/hand-derived spec that would 404").
- Scope it dev/test-only where the framework allows, so it needn't ship to production.

Present this as a recommendation with the diff and let the user decide — the skill does not
apply unrequested code changes (see "Recommend code changes for gaps" in `scan-planning.md`).
Make the suggestion good enough that saying yes is a one-step change, then rebuild and fetch
the served spec.

## Base path and context path

The most common accuracy failure is a base-path mismatch. HawkScan builds each request as the
configured host **plus the spec's operation path**; a spec whose paths omit the app's base or
context path 404s on every operation. Detect the app's base path during discovery and make
the effective `host + spec-path` land on real routes:

| Framework | Where the base/context path lives |
|-----------|-----------------------------------|
| Spring MVC | `server.servlet.context-path` (application.yml/properties) |
| Spring WebFlux | `spring.webflux.base-path` |
| Express | the mount prefix in `app.use('/api/v1', router)` |
| Django | the URL prefix in the root `urls.py` `include()` |
| ASP.NET | `UsePathBase(...)` / route prefix |
| Rails | `scope`/`namespace` in `config/routes.rb` |

Two ways to make it resolve — pick one and be consistent:
- Put the base path in `app.host` (e.g. `http://localhost:5000/api/v1`) and keep spec paths,
  `loginPath`, and `testPath` **relative**; or
- Keep `app.host` at the origin and ensure the spec's operation paths already include the base
  path (a framework-served spec usually does).

Do **not** split the difference — e.g. stripping the context path from `app.host` and
hardcoding it only into `loginPath`/`testPath`. That fixes auth but leaves every
`openApiConf` path unprefixed, which is exactly how a scan ends up 71% 404s while login still
works. If `hawk validate auth` misbehaves with a path component in `host`, resolve it without
desyncing the spec's base path — verify the outcome with the resolve check below.

## Mandatory: verify the spec resolves

Before the first real scan, prove the wired spec produces real requests — regardless of
source. This is the check that catches base-path mismatch, stale specs, and wrong hosts.

1. **Count sanity.** Spec operation count should be in the same ballpark as the route grep
   from discovery. A spec with far fewer/more paths than the code has is suspect.
2. **Resolve check.** Take 2–3 real operation paths **from the spec you're wiring** and
   request each **as the scanner will build it** — effective `host` + operation path — against
   the running app, both as the spec declares it and with the app's detected base/context path
   prepended. Substitute your own values for the placeholders; do not run them literally:
   ```bash
   # <spec-path>  = an operation path copied from the spec       (e.g. /authors)
   # <base-path>  = the app's detected base/context path, or empty if none  (e.g. /api/v1)
   curl -s -o /dev/null -w "%{http_code} %{url_effective}\n" "$SCAN_HOST<spec-path>"
   curl -s -o /dev/null -w "%{http_code} %{url_effective}\n" "$SCAN_HOST<base-path><spec-path>"
   ```
   If the spec-derived URL 404s while the base/context-path-prefixed variant returns a real
   status (200/401/403), the base path is wrong — fix `app.host` or the spec before scanning.
   A raw container 404 (e.g. Tomcat's default page) rather than an application response is a
   strong tell that the request never reached the app's routing.
3. After the scan, confirm with `hawk op scan uris <scanId>`: the scanned URIs should be the
   spec's real routes, not un-prefixed shadows of them.

## Deriving a spec by hand (no tooling)

When the stack has no OAS generator (or adding one is out of scope), build a minimal spec from
the route inventory discovery already produced. Keep it small and correct rather than
complete:

- One `paths` entry per real route; include path parameters as `{id}` style templates.
- Set `servers[].url` to the real base (including context path) — but remember HawkScan keys
  off `host + operation path`, so still run the resolve check; don't rely on `servers` alone.
- Include request bodies/params only where they matter for reaching the endpoint.
- Wire via `openApiConf.filePath` and verify as above.

A hand-derived spec is a maintenance liability — always prefer suggesting the framework
tooling (step 2) so the spec regenerates from code instead of drifting.

**A hand-derived spec still beats `hawk.spider.seedPaths`.** seedPaths only lists URLs to
visit — no methods, no request bodies, no path/query parameters — so a seedPaths-only scan
can GET a handful of collection endpoints but never exercises POST/PUT/PATCH, parameterized
routes, or request-body validation. That is why a spec-less scan collapses to a fraction of
the real surface — on a typical REST API that can be well under 10% of the routes reached.
Only use seedPaths as a supplement to a spec, or as a genuine last resort when even a
hand-derived spec is impossible.
