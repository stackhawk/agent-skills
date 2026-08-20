# Scan Planning Reference (Discovery)

Discovery is how the hawkscan skill decides *what* to scan and *how* before it writes or
edits a single `stackhawk.yml`. Run it in three situations:

- **First scan of a repo.** No `stackhawk.yml` exists yet (SKILL.md Step 1a / Step 2a) —
  discovery produces the surface inventory that Step 2a's config generation consumes.
- **The quality gate looped back with a structural gap.** A post-scan coverage check found
  routes the scan never reached, or a surface it didn't know existed. Re-run discovery
  against that specific gap rather than starting over.
- **The user asks to re-plan the scan.** New API surface added, a monorepo grew a service,
  an old assumption no longer holds.

Discovery is stateless: there is no plan file. `stackhawk.yml` is the only durable artifact,
and anything the user tells you that isn't a config field belongs as a comment in
`stackhawk.yml` or in the repo's `CLAUDE.md`/`AGENTS.md` — see "Ask, don't guess" below.

Work code-first, interactively: explore before asking, ask the user before guessing, and
never stall waiting for information you could get by reading three more files or asking one
direct question.

## Contents
- [Discover the app's API surfaces](#discover-the-apps-api-surfaces)
- [Recommend code changes for gaps](#recommend-code-changes-for-gaps)
- [Ask, don't guess](#ask-dont-guess)
- [Configure per surface](#configure-per-surface)
- [Cross-checking](#cross-checking)

---

## Discover the app's API surfaces

### Pass 1 — read what the repo already says

Most repos document themselves. Read these, in priority order, before exploring code —
treat what they say as authoritative and don't rediscover by grepping what a doc already
states:

| Source | Typically documents |
|--------|----------------------|
| `AGENTS.md` | run/build/test commands, layout, conventions |
| `CLAUDE.md` | same, written for agents — often the richest source |
| `GEMINI.md`, `.github/copilot-instructions.md` | agent run/build guidance |
| `.cursor/rules/*` | project conventions and setup steps |
| `README*` | quickstart, run command, default host/port |
| `CONTRIBUTING*` | local dev setup, how to run services and tests |
| `docs/` setup / quickstart / architecture pages | deeper API and service-boundary detail |

Harvest: run command + host/port, which API surfaces exist and where their source lives
(useful in a monorepo), and any documented spec location or dev/test credential. Read these
from the docs and config — discovery never starts the app to learn them. A
`docker-compose.yml` port mapping or an `.env`/`.env.example` `APP_URL` gives you the host
and port without running anything; starting the app is a scan-time step, not a discovery one.

### Pass 2 — explore code per surface type

For anything the docs didn't answer, find the surfaces the way a developer would: read
manifests, entry points, and route definitions. Identify **every** distinct API surface in
the repo — a service can have more than one (e.g. a REST API plus an internal gRPC service).
For each surface found, record its type and derive a route inventory using the matching
technique. The commands below are **illustrative starting points**, not fixed incantations:
point them at the repo's real source root and its actual spec/schema filenames — don't run
`src/`, `openapi.yaml`, or `schema.graphql` literally — and adjust the pattern to what the
code actually uses.

| Surface | Detection | Route inventory / derivation |
|---------|-----------|-------------------------------|
| REST — Spring | `@RestController`, `@Controller` classes | `grep -rEo '@(Get\|Post\|Put\|Delete\|Patch\|Request)Mapping' src/` — count matches |
| REST — Express/Node | `app.get/post/put/delete`, `router.get/post/...` | `grep -rEo "\.(get\|post\|put\|delete\|patch)\(" src/` (or route files under `routes/`) |
| REST — Rails | `config/routes.rb` | count route-verb lines: `grep -cE '^\s*(get\|post\|put\|patch\|delete)\s' config/routes.rb` |
| REST — Django | `urls.py` | count `path(`/`re_path(` entries: `grep -rc 'path(' **/urls.py` |
| REST — Go (gin/mux/chi) | `router.GET(`, `r.HandleFunc(`, `mux.NewRouter()` | `grep -rEo '\.(GET\|POST\|PUT\|DELETE\|PATCH)\(' .` |
| REST — .NET | `[HttpGet]`, `[HttpPost]`, `[Route(...)]` attributes | `grep -rEo '\[Http(Get\|Post\|Put\|Delete\|Patch)\]' .` |
| REST — OpenAPI spec | checked-in `openapi.{json,yaml,yml}`, `swagger*.{json,yaml}`; or served at `/v3/api-docs`, `/swagger.json`, `/openapi.json` once the app is running | count `paths:` entries: `yq '.paths | keys | length' openapi.yaml` (or the JSON equivalent). **A found spec is a hypothesis, not a win — see `openapi-specs.md` for getting an *accurate* one.** |
| GraphQL | schema files (`*.graphql`, `*.gql`); server libs in manifests (`graphql`, `apollo-server`, `graphql-yoga`, `graphene`, etc.); a `/graphql` endpoint | count root fields: `grep -A50 'type Query' schema.graphql \| grep -cE '^\s+\w+'` (repeat for `type Mutation`) |
| gRPC | `.proto` files; `grpc`/`protobuf` deps in the manifest | count `rpc` methods per service: `grep -c '^\s*rpc ' *.proto` |
| JSON-RPC / SOAP | fixed-path JSON-RPC dispatcher; WSDL files (`*.wsdl`), SOAP endpoint patterns | count `<operation` elements in the WSDL, or dispatcher method registrations |
| SPA (React, Vue, Angular, Svelte, Next, Nuxt) | client-rendered JS framework in the manifest; routes not present in the initial HTML | not route-counted the same way — see below |

For every surface, record whether an OpenAPI/schema/proto source is **verified-accurate**
(present *and* proven to resolve against the running app), **stale/unverified** (a spec
exists but its paths haven't been proven to match the app — the default state of any
checked-in file), or **missing**. Do not collapse the first two: a checked-in `openapi.yaml`
whose paths don't resolve is functionally missing and produces a wall of 404s. For REST
specifically, getting to *verified-accurate* — preferring a spec the framework serves from
the running app, suggesting the code/build change that makes it accurate, and running the
mandatory resolve-check — is its own procedure in `openapi-specs.md`; use it rather than
treating "a spec file exists" as done. That verdict, together with the route count and how it
was derived, is the contract the quality gate reuses after the scan to diff actual coverage
against this expectation — write it down precisely enough that someone re-running the same
grep gets the same number.

**SPA handling:** when a surface is a client-rendered JS front end, decide whether a backing
API also lives in this repo. The backing API is almost always the higher-DAST-value target —
scanning only the frontend surfaces header/CSP findings, not injection or auth bypass. Full
scenario breakdown (frontend-only, fullstack with API routes, frontend-only-third-party-
backend) and config templates live in `spa-scanning.md`; use it once a surface is identified
as a SPA rather than re-deriving that logic here.

## Recommend code changes for gaps

Some gaps can't be closed by configuration alone. When a surface has no reachable spec, or
its auth can't be exercised (no test credential, no way to obtain a token outside a browser
flow), recommend a concrete code change instead of guessing at a scan configuration that
won't actually reach the API surface. Typical recommendations:

- **No accurate OpenAPI spec.** This covers both "no spec at all" and "a spec exists but its
  paths don't resolve against the app" — treat them the same. The highest-value recommendation
  is a small code/build change that makes the framework *generate and serve* an accurate spec
  (idiomatic tooling exists for most stacks). Before deriving one by hand, also check whether
  the project publishes a spec *outside* the repo (a docs site, a `<project>/api-docs` repo, a
  release asset) — mature OSS projects often do. The full framework-generic procedure — probe
  for a served spec, the per-stack tooling matrix, how to write a concrete suggestion, the
  external-spec check, and the base-path/resolve verification — is in `openapi-specs.md`. Do
  that rather than wiring a stale checked-in file, or falling back to `seedPaths`, and hoping.
- **No test credential exists.** Recommend a test-only token issuer or seed script (a
  dev-only endpoint or fixture that mints a valid session/JWT) gated behind an environment
  check so it never ships to production.
- **GraphQL introspection disabled in the target environment.** Recommend enabling
  introspection for the scan environment only, or checking in the schema file if it isn't
  already.

These are recommendations only. Never apply an unrequested code change to close a coverage
gap — present the recommendation, explain the DAST value it unlocks, and let the user decide
whether to make the change.

## Ask, don't guess

Code exploration sometimes can't account for the whole URL space:

- A **monorepo slice** — the checked-out repo is one service among several, and its API is
  fronted by a gateway or composed with other services not present locally.
- A **gateway fronting upstreams** — the visible code is a thin proxy; the real route
  surface lives in services this repo doesn't contain.
- **Dynamic routing** — routes built from a database, a plugin registry, or a config file
  not checked into source control.

When code can't answer a surface question, ask the user directly — for the missing service's
repo, the gateway's route table, or the runtime detail that would resolve it. Don't guess a
plausible-looking answer and don't stall the whole discovery pass waiting on one open
question if other surfaces are ready to configure.

Once the user answers, that answer has nowhere else to live — there is no plan file to record
it in. Persist it as a comment next to the relevant `stackhawk.yml` block (e.g. `# gateway
also fronts the billing-service repo at github.com/org/billing — see route table in
#eng-platform`) or as a line in the repo's `CLAUDE.md`/`AGENTS.md` if it's a fact about the
repo rather than about one scan. Either way, the goal is the same: the next agent to run
discovery on this repo should never have to ask the same question twice.

## Configure per surface

Write **one `stackhawk.yml` config per API surface** (REST, GraphQL, gRPC, SOAP, SPA, ...).
Order them by DAST value, highest first: the primary or backing API surface goes first, a
SPA frontend goes last (per the SPA guidance above, it typically finds only header/CSP
issues). This order is not cosmetic — state it explicitly in the summary you show the user,
so the rationale for what scans first is visible, not implicit.

**Naming and platform mapping for multi-surface repos:** a single-surface repo uses plain
`stackhawk.yml`. With multiple surfaces, name each config `stackhawk-<surface>.yml` (e.g.
`stackhawk-rest.yml`, `stackhawk-graphql.yml`) and run each scan as
`hawk scan stackhawk-<surface>.yml`. All surfaces share one `applicationId`; give each
surface its own environment (e.g. `dev-rest`, `dev-graphql`). Findings compare scan-to-scan
within an environment, so per-surface envs keep each surface's history coherent instead of
interleaving a REST scan's baseline with a GraphQL scan's.

For each surface:

1. Wire the spec you found or confirmed in discovery: `openApiConf` for REST,
   `graphqlConf` for GraphQL, `grpcConf` + the `.proto` for gRPC, `soapConf` + the WSDL for
   SOAP. Use `hawk config show <field-path> --text` for the exact field shape — don't
   hand-write the block from memory. For REST, the spec must be *verified-accurate* before
   it's wired: get it and prove it resolves per `openapi-specs.md` (a wrong spec silently
   404s every operation), and make sure `app.host` and the spec agree on the base/context
   path.
2. Configure auth per Phase 1c in SKILL.md — one auth block per surface if surfaces have
   different login mechanisms (common when a gateway and an upstream service use different
   credential types).
3. Validate every surface's config before treating discovery as complete:
   ```bash
   hawk validate config <file>
   hawk validate api <file>       # when a spec is wired
   hawk validate auth <file>      # when authentication: is present
   ```

**Before the first scan of a fresh repo, present a one-screen summary and get the user's
confirmation.** The summary should state, per surface: the surface type, which config file
covers it, the scan order and why, the auth approach, the expected route count with how it
was derived (the same grep/spec-count evidence gathered above), and — for any REST surface
with a wired spec — the result of the mandatory resolve-check (e.g. "3/3 sample spec paths
resolved against host"; see `openapi-specs.md`). The resolve-check is the one thing that
catches a base-path mismatch before it wastes a whole scan, so its result belongs in the
summary rather than left to chance. Confirming this up front is cheap; discovering the scan
order, auth assumption, or a spec that 404s every path was wrong after a scan has already
run is not.

## Cross-checking

Don't configure `openApiConf`, `graphqlConf`, `grpcConf`, `soapConf`, or any other
spec-wiring block from memory alone — these shapes change across hawk releases. Two sources,
in order of preference:

1. **`hawk config show <section> --text`** — the canonical, version-matched recipe for the
   installed CLI. This is always correct for the hawk version actually in use and should be
   the default source for field syntax.
2. **docs.stackhawk.com**, via WebFetch or WebSearch when available — useful for narrative
   guidance `hawk config show` doesn't carry (why a shape works the way it does, worked
   examples for less common combinations). Prefer it over recalling the shape from training
   data whenever there's any doubt.

If the two disagree, trust `hawk config show` — it reflects the CLI version actually
installed, not a documentation snapshot that may be ahead of or behind it.
