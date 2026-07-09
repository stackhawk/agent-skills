---
name: hawkscan-ci
version: 2.3.2
description: >
  Use when the user wants to configure HawkScan in their CI/CD pipeline —
  triggers on "set up hawkscan in CI", "add stackhawk to my pipeline",
  "scan in CI", "configure github actions / gitlab / jenkins / circleci
  for hawkscan", "wire hawkscan into ci/cd", or any provider-named
  variant. Provider-agnostic: detects the CI system from repo files,
  edits the pipeline file in place to add a HawkScan job, prompts the
  user to set HAWK_API_KEY in their CI's native secrets engine (or an
  organizationally-approved external secrets manager), and wires
  commit-SHA + branch traceability. Defers every local-scan concern
  (stackhawk.yml, auth, findings, triage) to the hawkscan skill —
  requires a working local scan path before activating. Explicit
  trigger only; no autonomous code-change hook.
---

# HawkScan CI Skill

This skill graduates a working *local* HawkScan setup into a CI/CD
pipeline. It is a wrapper around the local-scan path the `hawkscan`
skill owns — it never generates `stackhawk.yml`, never picks auth
recipes, never parses findings. Its scope is the pipeline file alone.

**Hand-off rule:** if `stackhawk.yml` doesn't exist or doesn't validate,
the agent must invoke the `hawkscan` skill first. This skill does not
onboard apps from scratch.

---

## Step 0: Hand-off Check

Before doing anything CI-specific, confirm the local scan path is in
place. Run:

```bash
test -f stackhawk.yml || echo "MISSING_CONFIG"
timeout 30 hawk validate config stackhawk.yml 2>&1 | head -20
```

If `stackhawk.yml` is missing, validation fails, or `applicationId` is
still a placeholder (`${APP_ID}` with no real value, or literal
`your-app-id`):

> "I need a working local scan first. Run the hawkscan skill (or
> invoke it explicitly) to generate and validate `stackhawk.yml`, then
> come back here."

Stop. Do not proceed.

---

## Step 1: Detect the CI Provider

Glob the repo for known CI config locations:

```bash
ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null
ls .gitlab-ci.yml 2>/dev/null
ls Jenkinsfile* 2>/dev/null
ls .circleci/config.yml 2>/dev/null
ls azure-pipelines*.yml 2>/dev/null
ls bitbucket-pipelines.yml 2>/dev/null
ls .buildkite/pipeline.yml 2>/dev/null
ls .travis.yml 2>/dev/null
ls -d bamboo-specs 2>/dev/null
ls concourse/*.yml 2>/dev/null
ls -d harness 2>/dev/null
ls appspec.yml buildspec.yml 2>/dev/null
```

| Match | Provider |
|---|---|
| `.github/workflows/*.yml`, `*.yaml` | GitHub Actions |
| `.gitlab-ci.yml` | GitLab CI/CD |
| `Jenkinsfile`, `Jenkinsfile.*` | Jenkins |
| `.circleci/config.yml` | CircleCI |
| `azure-pipelines*.yml` | Azure Pipelines |
| `bitbucket-pipelines.yml` | Bitbucket Pipelines |
| `.buildkite/pipeline.yml` | Buildkite |
| `.travis.yml` | Travis CI |
| `bamboo-specs/` | Bamboo |
| `appspec.yml`, `buildspec.yml` | AWS CodeBuild / CodeDeploy |
| `concourse/*.yml` (heuristic — confirm with user) | Concourse |
| `harness/` | Harness |

- **One match** → use it.
- **Multiple matches** → ask: *"I see CI config for both X and Y in this repo. Which one should HawkScan run from?"*
- **No matches** → ask: *"I don't see any CI config in this repo. Which provider do you want to add HawkScan to? (GitHub Actions, GitLab, Jenkins, CircleCI, ...)"*

---

## Step 2: Plan the Integration

Three planning questions. Use the defaults if the user just says "sounds good".

**2a. Trigger** — when should the scan run?
> *"On pull requests, on pushes to main, on a daily schedule, or all three? Default: PRs + push to main."*

**2b. Blocking behavior** — what happens on findings?
> *"Should findings above the configured threshold fail the pipeline (exit code 42 → build failure), or warn-only (log the result, exit 0)? Default: fail the pipeline."*

**2c. Job placement** — where does the scan fit?
> *"Standalone parallel job (scans an ephemeral env or already-deployed preview), or chained after build (starts the app in the same job and scans it)? Default: chained-after-build."*

These answers parameterize Step 5.

---

## Step 3: Establish the API Key Secret

**The skill never sets the secret itself.** Prompt the user and tell
them exactly where to put it.

**Ask once:**

> *"Where should `HAWK_API_KEY` come from at runtime? Most teams use
> their CI provider's built-in secret store (recommended). If your org
> requires an external secrets manager (Vault, AWS Secrets Manager,
> GCP Secret Manager, Azure Key Vault, 1Password, Doppler), tell me
> which one and I'll generate the workflow to fetch from it instead."*

### Path A — CI-native secret store (default)

Print the exact command/UI step the user needs to run:

| Provider | Command / UI |
|---|---|
| GitHub Actions | `gh secret set HAWK_API_KEY` (paste interactively), or **Settings → Secrets and variables → Actions** |
| GitLab CI/CD | `glab variable set HAWK_API_ID <id> --masked --protected` AND `glab variable set HAWK_API_SECRET <secret> --masked --protected` — **mandatory key split** (GitLab's masker can't handle the `.` separators in `hawk.<id>.<secret>`). Reassemble in the job: `API_KEY="hawk.${HAWK_API_ID}.${HAWK_API_SECRET}"` |
| Jenkins | Credentials Store → Add credential → "Secret text", ID `HAWK_API_KEY` (UI only) |
| CircleCI | `circleci context store-secret <context-name> HAWK_API_KEY` (org-scoped Contexts), or **Project Settings → Environment Variables** (UI) |
| Azure Pipelines | `az pipelines variable create --name HAWK_API_KEY --secret true`, or variable group |
| Bitbucket | **Repository Settings → Repository variables** → add `HAWK_API_KEY`, check "Secured" |
| Others | See [`references/execution-shapes.md`](references/execution-shapes.md) |

### Path B — External secrets manager

If the user picked Vault / AWS SM / GCP SM / Azure KV / 1Password /
Doppler / etc., the workflow you write in Step 5 includes a fetch step
before the scan step. Fetch patterns:

- **HashiCorp Vault:** `vault kv get -field=hawk_api_key secret/ci/stackhawk`
- **AWS Secrets Manager:** `aws secretsmanager get-secret-value --secret-id stackhawk/hawk-api-key --query SecretString --output text`
- **GCP Secret Manager:** `gcloud secrets versions access latest --secret=hawk-api-key`
- **Azure Key Vault:** `az keyvault secret show --vault-name <vault> --name hawk-api-key --query value -o tsv`
- **1Password (GitHub Actions):** `1password/load-secrets-action@v2` with `op://<vault>/<item>/<field>` reference
- **Doppler:** `doppler secrets get HAWK_API_KEY --plain`

The user is responsible for the manager-side setup (storing the
secret, granting the runner read access). Call those out as out-of-band
actions in Step 6.

**Reminder regardless of path:** the secret must be set before the
first pipeline run, or the scan will fail with a 401.

---

## Step 4: Pick the Execution Shape

Three tiers, prefer highest the provider supports:

| Tier | Mechanism | When to use |
|---|---|---|
| 1. Native action | `stackhawk/hawkscan-action@v2` | GitHub Actions only |
| 2. Docker image | `stackhawk/hawkscan:latest` | Anywhere with Docker (GitLab, Jenkins, CircleCI, Azure, Bitbucket, Buildkite, AWS CodeBuild) |
| 3. Binary download | `hawk.manifest.json` → `download.stackhawk.com/hawk/<version>/<platform>/hawk` (self-contained binary) | Bare shell runners (Travis without sudo, some Spinnaker stages) |

**Track the latest stable scanner:**
- Image: use **`stackhawk/hawkscan:latest`** — HawkScan is a security scanner, so CI should run the newest stable build for the freshest checks.
- Action: pin the major (`@v2`) — auto-receives the newest action within v2.
- CLI: resolve the version + platform binary URL from the manifest (`download.stackhawk.com/hawkdocs/hawk.manifest.json` → `.latest.version` and asset `.url`); it's a single self-contained binary (no Java).
- **Need fully reproducible builds?** Pin an explicit version (`stackhawk/hawkscan:<X.Y.Z>`, `@vX.Y.Z`, or an image digest) instead — see [`references/execution-shapes.md`](references/execution-shapes.md).

See [`references/execution-shapes.md`](references/execution-shapes.md) for the full per-provider mapping.

---

## Step 5: Write or Patch the Workflow

Build the workflow block using the choices from Steps 2-4. The block
must do these things, in this order:

### 5.1 — Checkout the repo

Use the provider's standard checkout at the commit under test.

### 5.2 — Build / start the app

Detect the start pattern from the repo:

```bash
ls docker-compose.yml docker-compose.yaml compose.yml compose.yaml 2>/dev/null
test -f package.json && jq -r '.scripts | keys[]' package.json 2>/dev/null | grep -E '^(start|dev|serve)$'
test -f Makefile && grep -E '^(start|run|serve):' Makefile 2>/dev/null
ls pom.xml build.gradle build.gradle.kts 2>/dev/null
```

- **Docker Compose detected** → `docker compose up -d` + wait-for-it on the health endpoint. **Make sure the scanned image is built from the commit under test — build in-job (`--build` / a `build:` override) or build→push→pull; a stale or upstream `image:` tag gates code that isn't in this PR.** See [`references/app-startup-patterns.md`](references/app-startup-patterns.md) Pattern 1.
- **npm start script** → `npm install && npm start &` + wait-for-it.
- **Maven / Gradle** → `./mvnw spring-boot:run &` or `./gradlew bootRun &` + wait-for-it.
- **None detected** → ask the user for the start command.

App-startup pattern menu lives in [`references/app-startup-patterns.md`](references/app-startup-patterns.md).

### 5.2.5 — Confirm authenticated scans are self-contained

If the scan authenticates, the credential should come from the scan itself, not
the pipeline. HawkScan authenticates from the `authentication:` block in
`stackhawk.yml` — including `app.authentication.script` for multi-step
login/token-mint flows — owned by the `hawkscan` skill, so the same scan
authenticates identically on a laptop and in CI. Confirm that's in place rather
than replicating it in the workflow:

- `stackhawk.yml` already has a validated `authentication:` block → add nothing;
  the scan handles auth itself.
- Auth isn't configured, or the scan can't obtain the credential on its own →
  **route to the `hawkscan` skill** to add/repair the recipe, and to
  `stackhawk-data-seed` if the app needs seed *data* before authenticated routes
  return anything.
- A credential that genuinely can't live inside the scan (must be seeded
  out-of-band) → only then add a pre-scan step, preferring a committed
  `data-seed/` replay over bespoke scripting.

Don't replicate a token-mint step in the workflow — it belongs in the scan's
`authentication.script`. Full priority order + ownership table:
[`references/app-startup-patterns.md`](references/app-startup-patterns.md) Pattern 8.

### 5.3 — Export traceability env vars

```
COMMIT_SHA  = provider's commit SHA expression
BRANCH_NAME = provider's branch expression
```

Provider expression cheat sheet:

| Provider | `COMMIT_SHA` | `BRANCH_NAME` |
|---|---|---|
| GitHub Actions | `${{ github.sha }}` | `${{ github.head_ref \|\| github.ref_name }}` |
| GitLab CI | `${CI_COMMIT_SHA}` | `${CI_COMMIT_REF_NAME}` |
| Jenkins | `${env.GIT_COMMIT}` | `${env.BRANCH_NAME}` (multibranch) |
| CircleCI | `${CIRCLE_SHA1}` | `${CIRCLE_BRANCH}` |
| Azure Pipelines | `$(Build.SourceVersion)` | `$(Build.SourceBranchName)` |
| Bitbucket | `${BITBUCKET_COMMIT}` | `${BITBUCKET_BRANCH}` |
| Buildkite | `${BUILDKITE_COMMIT}` | `${BUILDKITE_BRANCH}` |
| Others | see [`references/execution-shapes.md`](references/execution-shapes.md) | see [`references/execution-shapes.md`](references/execution-shapes.md) |

**Do not set `HAWK_AGENT`.** That variable attributes scans to the AI
agent that triggered the work; a CI pipeline isn't an agent. The
`${HAWK_AGENT:none}` default already in `stackhawk.yml` resolves to
`none` for CI runs, which is the correct attribution. Leave it alone.

### 5.4 — Fetch external secret (Path B only)

If the user picked an external secrets manager in Step 3, insert the
provider-appropriate fetch step before the scan step, then export the
result as `HAWK_API_KEY` for the scan step.

### 5.5 — Invoke HawkScan

The scan step itself. Pass `HAWK_API_KEY` from the chosen secret
source via the provider's native secret reference (e.g.,
`${{ secrets.HAWK_API_KEY }}` for GHA, `$HAWK_API_KEY` exported from
the previous step for everyone else).

### 5.6 — Handle the exit code

Per the Step 2b choice:

- **Block:** let exit code propagate. Default behavior of all the
  invocation shapes — the action / docker / CLI all exit non-zero on
  42, the runner fails the job.
- **Warn-only:** downgrade only exit 42 to a warning; still fail on exit 1
  (config error, app unreachable, auth failure) — never declare success
  when the scan didn't run.
  Shell-based runners:
  ```bash
  set +e
  hawk scan
  HAWK_EXIT=$?
  case $HAWK_EXIT in
    0)  ;;
    42) echo "::warning::HawkScan found findings — review at the platform URL above." ;;
    *)  exit $HAWK_EXIT ;;   # exit 1 = config error / unreachable / auth — never swallow
  esac
  ```
  GitHub Actions has a native form (`continue-on-error: true`). Full per-provider warn-only patterns: [`references/failure-semantics.md`](references/failure-semantics.md).

### 5.7 — Upload the scan artifact

Per provider:

| Provider | Mechanism |
|---|---|
| GitHub Actions | `actions/upload-artifact@v4` |
| GitLab | `artifacts:` block in the job |
| Jenkins | `archiveArtifacts artifacts: 'hawkscan/*'` |
| CircleCI | `store_artifacts` step |
| Azure Pipelines | `PublishBuildArtifacts@1` task |
| Bitbucket | `artifacts:` block |

Path: the location the invocation shape produces (typically
`hawkscan-report/` for the action, or `$(pwd)/hawkscan/` for Docker).

Full per-provider workflow examples live in
[`references/execution-shapes.md`](references/execution-shapes.md).
Pick the example matching the detected provider, parameterize per
Steps 2-4, and write the result.

---

## Step 6: Verify and Report

After writing/patching the workflow file:

1. **Show the diff in chat.** Don't make the user open the file to see what changed.
2. **List out-of-band actions** the user still has to do:
   - Set the secret in the provider (Path A) or in the external manager + grant runner access (Path B)
   - If the scan job should be a required check, update branch protection rules in the provider UI
   - Confirm `stackhawk.yml` `applicationId` and `host` match the environment the pipeline will scan (preview URL vs ephemeral env vs local-in-runner)
3. **Set expectations:**
   > *"First pipeline run will be slower — HawkScan creates the App and Env in the platform if they don't exist, and the initial full scan has no prior baseline to diff against. Subsequent runs reuse the App and Env and are faster."*
4. **Stop.** Do not trigger the pipeline. Do not push the branch. Do not open the PR. The user owns the merge story.

---

## Common Mistakes to Avoid

- **Don't generate `stackhawk.yml`.** That's the `hawkscan` skill's surface. If the config is missing, hand off.
- **Don't set `HAWK_AGENT`.** CI pipelines aren't agents; the `${HAWK_AGENT:none}` default resolves correctly without intervention.
- **Use `stackhawk/hawkscan:latest` for the scanner image.** It's a security scanner — CI should run the newest stable build for the best detection. Pin an explicit version only when an org reproducibility mandate requires it.
- **Don't inline the API key.** Never, in any form. Always reference the provider's secret store or external secrets manager.
- **Don't try to set the secret autonomously.** Prompt the user and tell them where to put it.
- **Don't forget GitLab's key-split rule.** `HAWK_API_KEY` in the form `hawk.<id>.<secret>` triggers GitLab's variable-masking bug. Split into `HAWK_API_ID` + `HAWK_API_SECRET` and reassemble in the job.
- **Don't write `_STACKHAWK_GIT_*` tags from this skill.** Those live in `stackhawk.yml`; if they're missing, hand off to the `hawkscan` skill for the edit. The CI skill only exports the env vars the tags interpolate from.
- **Don't scan an image that doesn't contain the commit under test.** A published `image:` tag built elsewhere gates code that isn't in this PR. Building in-job (`--build` / a `build:` override) and build→push→pull both work; scanning a stale or upstream tag is the bug. See [`references/app-startup-patterns.md`](references/app-startup-patterns.md) Pattern 1.
- **Don't hand-roll auth bootstrapping in the pipeline.** The scan credential is the scan's job — it comes from `stackhawk.yml`'s `authentication:` block (including `authentication.script` for multi-step login/token-mint flows), owned by the `hawkscan` skill, so it's portable local↔CI. Confirm it's configured and route to `hawkscan` if not; add a pipeline step only for a credential that genuinely can't live in the scan. See Pattern 8.
- **Don't trigger the pipeline.** Editing the workflow file is the skill's full scope; running it is the user's call.
