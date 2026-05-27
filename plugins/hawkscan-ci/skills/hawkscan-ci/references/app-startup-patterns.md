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
