# App Startup Patterns Reference

The scan target needs to be reachable from the CI runner before `hawk scan` runs. This reference catalogs the common patterns and their tradeoffs.

## Pattern Selection

| Repo signals | Pattern |
|---|---|
| `docker-compose.yml` / `compose.yml` at root | Docker Compose + wait-for-it |
| `package.json` with `start` / `dev` script | Build-then-run (Node) |
| `pom.xml` or `build.gradle*` with Spring Boot | Build-then-run (JVM) |
| `Dockerfile` only (no compose) | Run image as background container |
| App already deployed to ephemeral env | Scan-existing-host (no startup step) |
| None of the above | Ask the user for the start command |

## Pattern 1 — Docker Compose

Most common; works on every provider that has Docker. Assume the compose file exposes the app on a known port (e.g., `8080`).

```bash
docker compose up -d
# wait for app to be ready before scanning
timeout 60 bash -c 'until curl -fsS http://localhost:8080/health; do sleep 2; done'
```

**Build the code under test — don't scan a pulled image.** If the compose service for the app under test declares `image:` pointing at a published registry tag (e.g. a `:latest` or `:<branch>` image) with **no** `build:` block, `docker compose up` pulls *upstream's* published build. The scan then exercises that image, not the code in the checkout — so any fix made in the same pipeline is invisible to the scan, and a fix-and-rescan loop silently verifies nothing. Force a local build one of three ways:

- `docker compose up -d --build` — but `--build` only rebuilds services that already have a `build:` stanza; a service defined purely by `image:` ignores it.
- Add a `build:` block for the app service via a compose override (`docker-compose.override.yml` with `build: { context: ., dockerfile: ... }`), which `up` merges automatically.
- Build the image explicitly earlier in the job and point the service's `image:` at that local tag.

Confirm the app-under-test service actually builds from the checkout before trusting the scan.

**Wait-for-it variants:**
- `curl --fail --silent --max-time 2` in a loop is the simplest.
- `dockerize -wait tcp://localhost:8080 -timeout 60s` if `dockerize` is in the image.
- `wait-for-it.sh localhost:8080 -t 60` is also common.

**Cleanup:** in a single-job runner, you don't need to teardown — the runner is ephemeral. If running multiple test stages in the same job, add `docker compose down -v` after the scan step.

## Pattern 2 — GitLab `services:` keyword

GitLab's `services:` runs sidecar containers alongside the job container. Useful when the app under test is fully containerized.

```yaml
hawkscan:
  image: stackhawk/hawkscan:latest
  services:
    - name: my-org/my-app:latest
      alias: app
  script:
    - hawk scan
```

The scan target becomes `http://app:8080` (the alias), not `localhost`. Update `stackhawk.yml`'s `host` accordingly — typically by setting `APP_HOST=http://app:8080` as a job variable.

## Pattern 3 — GitHub Actions `services:` map

GHA jobs can declare service containers in the job spec:

```yaml
jobs:
  hawkscan:
    runs-on: ubuntu-latest
    services:
      app:
        image: my-org/my-app:latest
        ports:
          - 8080:8080
        options: >-
          --health-cmd "curl -f http://localhost:8080/health || exit 1"
          --health-interval 5s
          --health-retries 12
    steps:
      - uses: actions/checkout@v4
      - uses: stackhawk/hawkscan-action@v2.5.0
        with:
          apiKey: ${{ secrets.HAWK_API_KEY }}
```

GHA waits for service-container health before running steps — no manual wait-for-it needed.

## Pattern 4 — Build-then-run (Node)

```bash
npm ci
npm run build      # if build step exists
npm start &
APP_PID=$!
timeout 60 bash -c 'until curl -fsS http://localhost:3000; do sleep 2; done'

# ...scan...

kill $APP_PID 2>/dev/null || true
```

**Pitfalls:**
- `npm start &` returns immediately — the wait-for-it loop is non-optional.
- Without `kill $APP_PID` you'll leak the process, which is fine for an ephemeral runner but breaks self-hosted/long-lived runners.

## Pattern 5 — Build-then-run (JVM / Spring Boot)

```bash
./mvnw -B -DskipTests package
nohup java -jar target/*.jar > app.log 2>&1 &
APP_PID=$!
timeout 90 bash -c 'until curl -fsS http://localhost:8080/actuator/health; do sleep 3; done'
```

Or Gradle:

```bash
./gradlew -q bootRun &
APP_PID=$!
timeout 90 bash -c 'until curl -fsS http://localhost:8080/actuator/health; do sleep 3; done'
```

`bootRun` is more wasteful than running a built JAR (it re-compiles every run); prefer the JAR pattern in CI.

## Pattern 6 — Run a built Docker image

If the repo's CI already builds an image (`docker build -t app:test .` earlier in the pipeline):

```bash
docker run -d --rm --name app -p 8080:8080 app:test
timeout 60 bash -c 'until curl -fsS http://localhost:8080/health; do sleep 2; done'

# ...scan...

docker stop app
```

## Pattern 7 — Scan-existing-host (ephemeral env / preview deployment)

If the pipeline deploys to an ephemeral environment before scanning (preview URL per PR, dev cluster, etc.), the scan step skips startup entirely — just set `APP_HOST` to the deployed URL:

```yaml
- name: Run HawkScan against preview
  uses: stackhawk/hawkscan-action@v2.5.0
  env:
    APP_HOST: ${{ steps.deploy.outputs.preview_url }}
  with:
    apiKey: ${{ secrets.HAWK_API_KEY }}
```

`stackhawk.yml`'s `host:` field must use `${APP_HOST:...}` interpolation for this to work — the `hawkscan` skill already enforces that pattern.

## Pattern 8 — Bootstrap auth at runtime

Every pattern above stops at *the app is reachable*. An **authenticated** scan needs one more rung: a credential that exists at scan time. In CI the database is usually ephemeral and freshly created, so no user, token, or API key exists yet. Skip this and the scan runs unauthenticated — the spider stalls at login walls, coverage collapses, and a green result is a false all-clear.

This step belongs **after** the readiness wait and **before** the scan. Two shapes:

### 8a — Replay committed seed data

If the repo has a `data-seed/` directory (produced by the `stackhawk-data-seed` skill), it holds an ordered manifest of SQL/HTTP/gRPC/shell steps that create the minimal authenticated entities (a user, a parent org/tenant, one scannable resource). Replay it against the running stack, then let the scan's auth recipe use the resulting credentials.

- `data-seed/` **present** → add a job step that replays the manifest (per its `README.md`) against the now-running services.
- App needs authenticated routes but `data-seed/` is **absent** → this isn't a pipeline problem. Route the user to the `stackhawk-data-seed` skill to generate the seed artifacts first, then resume here.
- **CI caveat:** `stackhawk-data-seed`'s `.data-seed-credentials.env` handoff file is gitignored, so it is **not** on the runner. The credential *values* must be deterministic (reconstructed from the committed seed scripts / `credentials.env.example`) or supplied from the CI secret store — never assume the local `.env` travels to CI.

### 8b — Mint a credential through the app's own API

When the app has no seedable datastore credential but exposes a registration/login/token endpoint, drive that flow in a job step to obtain a runtime credential (session cookie, JWT, or API token). Many apps protect these endpoints with CSRF, so the flow is usually: fetch a CSRF token → register or log in a throwaway user (the ephemeral DB makes the username free every run) → exchange for the scan credential.

Skeleton — **placeholder paths; substitute the app's real endpoints and field names:**

```bash
set -euo pipefail
BASE=http://localhost:8080
JAR=$(mktemp)

CSRF=$(curl -s -c "$JAR" -b "$JAR" "$BASE/<csrf-endpoint>" | jq -r .token)
curl -s -c "$JAR" -b "$JAR" -X POST "$BASE/<register-or-login>" \
  -H 'Content-Type: application/json' -H "<csrf-header>: $CSRF" \
  -d '{"username":"<throwaway>","password":"<throwaway>"}' -o /dev/null

CSRF=$(curl -s -c "$JAR" -b "$JAR" "$BASE/<csrf-endpoint>" | jq -r .token)
TOKEN=$(curl -s -c "$JAR" -b "$JAR" -X POST "$BASE/<mint-token>" \
  -H 'Content-Type: application/json' -H "<csrf-header>: $CSRF" \
  -d '{"label":"hawkscan-ci"}' | jq -r .<secret-field>)
rm -f "$JAR"

[ -n "$TOKEN" ] && [ "$TOKEN" != null ] || { echo "token mint failed" >&2; exit 1; }
# Mask the secret in logs and export it for the scan step using the provider's
# own mechanism (e.g. GitHub Actions: `echo "::add-mask::$TOKEN"` then write to
# $GITHUB_ENV; GitLab: a masked job variable; etc.).
```

### The seam — who owns what

| Concern | Owner |
|---|---|
| *Where* the bootstrap step goes, ordering, log-masking, exporting the credential to the scan step | **this skill** (CI plumbing) |
| *What* entities/credentials to seed and the seed artifacts themselves | `stackhawk-data-seed` |
| *Which* auth recipe consumes the credential (`stackhawk.yml` auth block, env interpolation) | `hawkscan` |

This skill guarantees only that the credential **exists at runtime and is exported** under the env var the `stackhawk.yml` auth recipe interpolates. It does not pick the recipe or invent the seed. If you can't tell whether the app even needs authenticated scanning, that's a `hawkscan`-skill question — hand off rather than guess.

## Networking Gotchas

| Runner type | Reaching `localhost` from a scanner container |
|---|---|
| Linux GHA runner, GitLab DinD, CircleCI machine executor | `--network host` works; `localhost` = host loopback |
| Docker Desktop runners (macOS, Windows) | Use `http://host.docker.internal:<port>`, not `localhost` |
| Kubernetes-based runners (Jenkins on EKS, Argo Workflows) | Use the in-pod service DNS or the sidecar pattern; `--network host` won't help |
| CircleCI `setup_remote_docker` | Apps started in the build container are NOT reachable from the remote Docker daemon — run the app in the remote Docker host instead, or switch to the `machine:` executor |

## Health-Check Endpoints

The wait-for-it loops above assume a health endpoint exists. Common defaults:

| Framework | Default health endpoint |
|---|---|
| Spring Boot Actuator | `/actuator/health` |
| Express + healthcheck middleware | `/healthz` or `/health` |
| Next.js / Vercel-style | `/api/health` if defined, else `/` |
| ASP.NET Core | `/health` if `MapHealthChecks("/health")` is wired |
| Spec-driven API (no `/health`) | Poll the served OpenAPI/Swagger JSON for `200` — `/openapi.json`, `/v3/api-docs` (Spring), `/swagger.json`, or the app's documented spec path. Doubles as proof the API layer is up, not just the port. |
| Anything else | Try `/`, fall back to TCP-port reachability (`nc -z localhost 8080`) |

If no health endpoint exists and the user can't add one, fall back to TCP probing:

```bash
timeout 60 bash -c 'until nc -z localhost 8080; do sleep 2; done'
```

## Common Mistakes

- **Not waiting for the app to be ready.** Scanning before the app accepts connections produces a "Connection refused" exit-1 failure, not a clean scan. Always wait.
- **`localhost` from inside a scanner container without `--network host`.** Scanner can't reach the host's `localhost`. Fix with `--network host` (Linux), `host.docker.internal` (macOS/Windows runners), or service-container linking.
- **Spider can't find auth routes because the app is partially started.** Login pages render before the database is ready; the spider thinks the API is broken. Health-check the *backing services too*, not just the HTTP port.
- **`npm start &` without `wait-for-it`.** The `&` returns immediately; the scan starts against a not-yet-listening port. Always pair with a wait loop.
- **Leaving the app running across steps without `set -e`.** A failed wait loop should fail the job. With `set -e` and `timeout 60`, the job dies if the app never comes up — which is the desired behavior.
- **Scanning a pulled image instead of your built code.** If the app-under-test service in the compose file is defined by `image:` (a published registry tag) with no `build:` block, `docker compose up` runs upstream's code — your changes, including security fixes, are never scanned, and a fix-and-rescan loop silently verifies nothing. Add `--build` (with a `build:` stanza), a compose `build:` override, or build the image explicitly. See Pattern 1.
- **Running an authenticated scan with no runtime credential.** In CI the database is fresh — no user or token exists until you create one. Scanning without bootstrapping auth (Pattern 8) yields an unauthenticated crawl that stalls at login walls; coverage tanks and a clean result is meaningless. Seed (`data-seed/` replay, or route to `stackhawk-data-seed`) or mint the credential via the app's API before the scan, and confirm `hawk validate auth` passes.
