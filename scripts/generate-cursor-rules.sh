#!/usr/bin/env bash
set -euo pipefail

# ─── Cursor Rule Generation Script ───
# Transforms canonical SKILL.md + references/*.md into Cursor .mdc format.
# Run from repo root: bash scripts/generate-cursor-rules.sh
#
# Each entry in MAPPINGS defines:
#   source_file|output_name|cursor_description|globs (comma-separated, or empty)|alwaysApply (true or false, default false)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/cursor/.cursor/rules"
PLUGINS_DIR="${REPO_ROOT}/plugins"

# ─── Frontmatter Mapping Config ───
# Format: source_path|output_name|description|globs|alwaysApply
# Source paths are relative to PLUGINS_DIR
MAPPINGS=(
  "hawkscan/skills/hawkscan/SKILL.md|stackhawk-hawkscan|AUTONOMOUS: After completing any code change (feature, bugfix, refactor), run the full HawkScan security loop — configure, scan, fix all reported vulnerabilities (not just your changes), rescan to verify. Do not ask permission. Also trigger for \"hawkscan\", \"stackhawk\", \"stackhawk.yml\", \"DAST\", \"security scan\", \"scan my API/app\".|**/stackhawk.yml,**/stackhawk-*.yml|true"
  "hawkscan/skills/hawkscan/references/cli-reference.md|stackhawk-hawkscan-cli|hawk CLI reference: scan commands and flags (--json-output, --verbose, --debug, --trace), validate commands (config, api, auth), perch daemon mode, diagnostic commands, exit codes, subcommand options for scan scope, scanner behavior, output artifacts, and git integration.||false"
  "hawkscan/skills/hawkscan/references/config-patterns.md|stackhawk-hawkscan-config|stackhawk.yml cross-cutting config patterns: env var interpolation (\${VAR:default}, whole-value rule), multi-environment config (host interpolation vs file layering), common config-time gotchas. For per-field syntax, use \`hawk config show <field-path> --text\`. For authentication, follow Phase 1c in SKILL.md.|**/stackhawk.yml,**/stackhawk-*.yml|false"
  "hawkscan/skills/hawkscan/references/docker-usage.md|stackhawk-hawkscan-docker|HawkScan Docker usage: standard container run, scanning localhost apps, custom config files, environment variables, CI Docker environments, network configuration for host access.|**/Dockerfile*,**/docker-compose*|false"
  "hawkscan/skills/hawkscan/references/findings-and-fixes.md|stackhawk-hawkscan-findings|HawkScan findings reference: JSON output schema (--json-output), field reference, thresholdResult to exit code mapping, agentic fix task format, priority rules (severity, exploitability ordering), common findings quick reference (SQL injection, XSS, IDOR, path traversal, broken auth, information disclosure).||false"
  "hawkscan/skills/hawkscan/references/high-iteration-findings.md|stackhawk-hawkscan-high-iteration|HawkScan high-iteration findings guide: per-finding fix guidance for CSP, CORS, Auth (unprotected endpoint), and Missing Security Headers. Covers why each finding fires, minimal done fix, curl verification command, rescan expectation, and escalation threshold (2 rescans for CSP/CORS/Auth, 1 for Missing Headers). Use when an agent is iterating on a security finding and needs to know what done looks like or when to stop.||false"
  "hawkscan/skills/hawkscan/references/installation.md|stackhawk-hawkscan-install|HawkScan installation: Homebrew (macOS), package installers (all platforms), prerequisites (Java 17+), verification (hawk version).||false"
  "hawkscan/skills/hawkscan/references/false-positives.md|stackhawk-hawkscan-false-positives|HawkScan false positives guide: identifying false positives, deciding fix vs suppress, excludePaths and failureThreshold config, excluding scan plugins, reporting accepted risk.||false"
  "hawkscan/skills/hawkscan/references/platform-model.md|stackhawk-hawkscan-model|HawkScan StackHawk platform model: Org → App → Env → Scan hierarchy, what goes in stackhawk.yml vs what doesn't, finding triage state machine (New/Accepted/False Positive/Reopened) and agent behavior per state, tags for commit traceability (_STACKHAWK_GIT_COMMIT_SHA, _STACKHAWK_GIT_BRANCH), technology flags (platform UI only — no API yet), hawk rescan --scan-id for fast fix verification in the agentic loop, create vs reuse decision trees for Apps and Envs.||false"
  "api/skills/api/SKILL.md|stackhawk-api|Use when querying the StackHawk platform for security reporting, findings analysis, or app management. Triggers include \"stackhawk api\", \"security posture\", \"findings report\", \"show me findings\", \"untriaged findings\", \"which apps\", \"scan history\", \"security dashboard\", \"triage\", \"what needs attention\". Prefers the hawkop CLI when installed; falls back to raw REST calls otherwise. Do NOT use for scanning — use the stackhawk-hawkscan rule for \"scan my app\", \"hawkscan\", \"stackhawk.yml\", \"DAST\".||false"
  "api/skills/api/references/hawkop-shortcuts.md|stackhawk-api-hawkop|HawkOp CLI shortcuts for the StackHawk API: user intent → single hawkop command mapping for scan drill-down, app/user/team/policy/repo/oas/config/secret/audit listing, hosted scan control, env management. Replaces multi-step curl+jq pipelines. Use first when hawkop is installed; fall back to raw API (stackhawk-api-auth, stackhawk-api-endpoints) when hawkop doesn't wrap an endpoint.||false"
  "api/skills/api/references/api-auth.md|stackhawk-api-auth|StackHawk API authentication reference (fallback when hawkop is not installed): JWT token flow, HAWK_API_KEY setup, hawk_api and hawk_api_all_pages helper scripts, token refresh, V1/V2 pagination, 401/403 error diagnosis.||false"
  "api/skills/api/references/api-endpoints.md|stackhawk-api-endpoints|StackHawk API endpoint catalog (raw REST, used when hawkop doesn't wrap the endpoint): authentication, applications, environments, scan results drill-down chain (scans -> alerts -> findings -> evidence), organization-wide queries, teams, V1/V2 pagination patterns.||false"
  "api/skills/api/references/reporting-recipes.md|stackhawk-api-recipes|StackHawk API reporting recipes: org security posture summary, app deep dive (scan -> alerts -> findings), stale apps detection, scan diff (what changed since last scan). Pre-built jq compositions using hawk_api helpers. Prefer hawkop shortcuts (stackhawk-api-hawkop) for the deep-dive chain; use these recipes for the per-env untriaged posture view.||false"
  "hawkscan-ci/skills/hawkscan-ci/SKILL.md|stackhawk-hawkscan-ci|Use when the user wants to configure HawkScan in their CI/CD pipeline — triggers on \"set up hawkscan in CI\", \"add stackhawk to my pipeline\", \"scan in CI\", \"configure github actions / gitlab / jenkins / circleci for hawkscan\", \"wire hawkscan into ci/cd\". Provider-agnostic: detects the CI system, edits the pipeline file in place to add a HawkScan job, prompts for HAWK_API_KEY storage (CI-native secrets store or external secrets manager), wires commit-SHA + branch traceability. Defers all local-scan concerns (stackhawk.yml, auth, findings, triage) to stackhawk-hawkscan.|.github/workflows/**,.gitlab-ci.yml,Jenkinsfile*,.circleci/config.yml,azure-pipelines*.yml,bitbucket-pipelines.yml,.buildkite/pipeline.yml,.travis.yml,appspec.yml,buildspec.yml|false"
  "hawkscan-ci/skills/hawkscan-ci/references/execution-shapes.md|stackhawk-hawkscan-ci-execution-shapes|HawkScan CI execution shapes reference: native action (stackhawk/hawkscan-action) vs Docker image (stackhawk/hawkscan) vs CLI download; pinning strategy; per-provider quick-reference recipes for GitHub Actions, GitLab CI, Jenkins, CircleCI, Azure Pipelines, Bitbucket, Buildkite, Travis, AWS CodeBuild; SARIF / Code Scanning notes.||false"
  "hawkscan-ci/skills/hawkscan-ci/references/app-startup-patterns.md|stackhawk-hawkscan-ci-app-startup|HawkScan CI app-startup patterns reference: Docker Compose + wait-for-it, GitLab services keyword, GitHub Actions services map, build-then-run (Node, JVM), run-a-built-image, scan-existing-host (ephemeral env / preview deployment), networking gotchas (--network host vs host.docker.internal), health-check endpoint conventions.||false"
  "hawkscan-ci/skills/hawkscan-ci/references/failure-semantics.md|stackhawk-hawkscan-ci-failure|HawkScan CI failure semantics reference: exit codes 0/1/42, failureThreshold tuning, block-on-42 vs warn-only vs scheduled-baseline modes, retry strategy (don't retry 42), caching strategy (cache CLI/image, never findings), scheduled-vs-PR-trigger tradeoffs.||false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/SKILL.md|stackhawk-data-seed|Use when the user says \"set up data for HawkScan\", \"my scan has no data to hit\", \"seed this repo for scanning\", or as a planned first-time-setup step before invoking hawkscan on a fresh repo. Reads a target repo (and any upstream service repos it depends on), proposes the minimum seed entities required for authenticated scanning, dialogs with the user, then emits checked-in artifacts (SQL / HTTP / gRPC / Mongo / shell steps) plus a manifest.yaml and a .data-seed-credentials.env handoff file. Does NOT write stackhawk.yml (hawkscan owns that), does NOT run the artifacts (deferred to a future Runner), does NOT start the environment. NOT autonomous — explicit user invocation only.|**/data-seed/manifest.yaml,**/.data-seed-credentials.env|false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/references/discovery.md|stackhawk-data-seed-discovery|Per-ecosystem storage-type and API-surface detection for the stackhawk-data-seed skill: PostgreSQL/MySQL/SQLite/Mongo/DynamoDB/Cosmos signals; OpenAPI/protobuf/GraphQL; auth-signal detection; environment config and docker-compose service+port extraction; integration test fixture locations; what to do when discovery is ambiguous; edge cases (monorepos, generated code, vendored deps).||false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/references/manifest-schema.md|stackhawk-data-seed-manifest|Data seed manifest schema (Contract B) full reference: top-level structure (version, targets, prerequisites, steps, outputs); step schema with all fields (target as scalar string, idempotency as scalar strategy name); supported step types (sql, http, grpc, mongo, shell); idempotency primitives (check_sql, check_http, check_command, none); dependency model; self-validation rules; complete example; forbidden patterns.|**/data-seed/manifest.yaml|false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/references/cross-repo-deps.md|stackhawk-data-seed-cross-repo|Cross-repo upstream service dep resolution for the stackhawk-data-seed skill: detection signals (docker-compose, env URLs, gRPC stubs, imported clients); resolution flow (sibling-directory search, DATA_SEED_REPO_<NAME> env vars, user-confirmation fallback); naming normalization rules; remote-only upstream handling; monorepo handling; confirmation patterns; edge cases.||false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/references/idempotency-patterns.md|stackhawk-data-seed-idempotency|Per-dialect idempotency patterns for data-seed steps: SQL idioms (Postgres ON CONFLICT, MySQL INSERT IGNORE, SQLite INSERT OR IGNORE); HTTP (PUT over POST); gRPC (Get-then-Create); Mongo (upsert); shell escape hatch conventions; predicate-design rules; anti-patterns to avoid.|**/data-seed/**/*.sql,**/data-seed/**/*.http|false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/references/example-walkthrough.md|stackhawk-data-seed-walkthrough|End-to-end worked example of the stackhawk-data-seed skill: discovery output for a two-service architecture (gateway-api + auth-service + inventory-service), cross-repo dep resolution, minimal seed proposal dialog, full content of every emitted artifact (manifest.yaml + per-service SQL/HTTP files + credentials handoff), manual replay walkthrough, validation criteria.||false"
)

# ─── Generate ───

mkdir -p "${OUTPUT_DIR}"

# Clean old generated files
rm -f "${OUTPUT_DIR}"/*.mdc

error_count=0

for mapping in "${MAPPINGS[@]}"; do
  IFS='|' read -r source_path output_name description globs always_apply <<< "${mapping}"

  source_file="${PLUGINS_DIR}/${source_path}"

  if [[ ! -f "${source_file}" ]]; then
    echo "ERROR: Source file not found: ${source_file}" >&2
    error_count=$((error_count + 1))
    continue
  fi

  output_file="${OUTPUT_DIR}/${output_name}.mdc"

  # Read source body, stripping any existing YAML frontmatter
  body=$(awk '
    BEGIN { in_frontmatter=0; past_frontmatter=0 }
    /^---$/ && !past_frontmatter { in_frontmatter = !in_frontmatter; if (!in_frontmatter) { past_frontmatter=1 }; next }
    in_frontmatter { next }
    { past_frontmatter=1; print }
  ' "${source_file}")

  # Build globs YAML
  globs_yaml=""
  if [[ -n "${globs}" ]]; then
    globs_yaml=$'\nglobs:'
    IFS=',' read -ra glob_array <<< "${globs}"
    for g in "${glob_array[@]}"; do
      globs_yaml="${globs_yaml}"$'\n'"  - \"${g}\""
    done
  else
    globs_yaml=$'\nglobs:'
  fi

  # Write .mdc file
  cat > "${output_file}" <<FRONTMATTER
---
description: >
  ${description}${globs_yaml}
alwaysApply: ${always_apply:-false}
---
${body}
FRONTMATTER

  echo "Generated: ${output_file##*/}"
done

if [[ ${error_count} -gt 0 ]]; then
  echo "ERROR: ${error_count} source file(s) not found. See errors above." >&2
  exit 1
fi

echo "Done. Generated $(ls "${OUTPUT_DIR}"/*.mdc 2>/dev/null | wc -l | tr -d ' ') Cursor rules in ${OUTPUT_DIR}/"
