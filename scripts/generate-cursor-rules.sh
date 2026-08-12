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
  "hawkscan/skills/hawkscan/SKILL.md|stackhawk-hawkscan|HawkScan DAST security scanning. Use when the user asks to run or perform a security or DAST scan, to test an app or API for vulnerabilities, or to verify a vulnerability is fixed — and proactively right after you complete a code change (feature, bugfix, refactor); \"done\" means \"done and secure\" (configure, scan, fix all reported vulnerabilities, rescan; do not ask permission). Do NOT use for: informational questions about what HawkScan is or detects; editing stackhawk.yml or other config without running a scan; querying existing findings, security posture, or scan history (use the stackhawk-api rule); documentation-only changes; or installing the CLI.|**/stackhawk.yml,**/stackhawk-*.yml|true"
  "hawkscan/skills/hawkscan/references/cli-reference.md|stackhawk-hawkscan-cli|hawk CLI reference: scan commands and flags (--json-output, --verbose, --debug, --trace), validate commands (config, api, auth), perch daemon mode, diagnostic commands, exit codes, subcommand options for scan scope, scanner behavior, output artifacts, and git integration.||false"
  "hawkscan/skills/hawkscan/references/config-patterns.md|stackhawk-hawkscan-config|stackhawk.yml cross-cutting config patterns: env var interpolation (\${VAR:default}, whole-value rule), multi-environment config (host interpolation vs file layering), common config-time gotchas. For per-field syntax, use \`hawk config show <field-path> --text\`. For authentication, follow Phase 1c in SKILL.md.|**/stackhawk.yml,**/stackhawk-*.yml|false"
  "hawkscan/skills/hawkscan/references/docker-usage.md|stackhawk-hawkscan-docker|HawkScan Docker usage: standard container run, scanning localhost apps, custom config files, environment variables, CI Docker environments, network configuration for host access.|**/Dockerfile*,**/docker-compose*|false"
  "hawkscan/skills/hawkscan/references/findings-and-fixes.md|stackhawk-hawkscan-findings|HawkScan findings reference: JSON output schema (--json-output), field reference, thresholdResult to exit code mapping, agentic fix task format, priority rules (severity, exploitability ordering), common findings quick reference (SQL injection, XSS, IDOR, path traversal, broken auth, information disclosure).||false"
  "hawkscan/skills/hawkscan/references/high-iteration-findings.md|stackhawk-hawkscan-high-iteration|HawkScan high-iteration findings guide: per-finding fix guidance for CSP, CORS, Auth (unprotected endpoint), and Missing Security Headers. Covers why each finding fires, minimal done fix, curl verification command, rescan expectation, and escalation threshold (2 rescans for CSP/CORS/Auth, 1 for Missing Headers). Use when an agent is iterating on a security finding and needs to know what done looks like or when to stop.||false"
  "hawkscan/skills/hawkscan/references/installation.md|stackhawk-hawkscan-install|HawkScan installation: Homebrew (macOS), manifest-driven binary download, package installers (.pkg/.msi), verification (hawk version). Self-contained binary — no separate Java install needed.||false"
  "hawkscan/skills/hawkscan/references/false-positives.md|stackhawk-hawkscan-false-positives|HawkScan false positives guide: identifying false positives, deciding fix vs suppress, excludePaths and failureThreshold config, excluding scan plugins, reporting accepted risk.||false"
  "hawkscan/skills/hawkscan/references/platform-model.md|stackhawk-hawkscan-model|HawkScan StackHawk platform model: Org → App → Env → Scan hierarchy, what goes in stackhawk.yml vs what doesn't, finding triage state machine (New/Accepted/False Positive/Reopened) and agent behavior per state, tags for commit traceability (_STACKHAWK_GIT_COMMIT_SHA, _STACKHAWK_GIT_BRANCH), technology flags (platform UI only — no API yet), hawk rescan --scan-id for fast fix verification in the agentic loop, create vs reuse decision trees for Apps and Envs.||false"
  "hawkscan/skills/hawkscan/references/scan-planning.md|stackhawk-hawkscan-scan-planning|HawkScan scan-planning (discovery) reference: code-first discovery of an app's API surfaces before writing or editing stackhawk.yml — reading repo docs first, per-framework route inventory, recommending code changes for structural gaps, asking the user instead of guessing, and producing a per-surface stackhawk.yml config. Use for the first scan of a repo, a quality-gate structural gap, or a user-requested re-plan.||false"
  "hawkscan/skills/hawkscan/references/openapi-specs.md|stackhawk-hawkscan-openapi-specs|HawkScan OpenAPI spec accuracy reference: framework-generic procedure for getting an accurate OpenAPI spec into openApiConf for a REST surface — prefer a spec the running app serves, suggest the code/build change that makes the framework generate one, verify it resolves against the app (base/context path), and derive one by hand only as a last resort. Use whenever wiring or fixing openApiConf, or when a scan's spec paths return 404s.||false"
  "hawkscan/skills/hawkscan/references/scan-quality.md|stackhawk-hawkscan-scan-quality|HawkScan scan-quality (post-scan quality gate) reference: run after every scan and rescan, before findings become fix tasks. Derives a fresh coverage expectation each run (spec-wired or route-inventory), the four coverage checks, and a bounded, additive-only stackhawk.yml config iteration to close gaps — never blocks a real finding from being reported and fixed.||false"
  "hawkscan/skills/hawkscan/references/authz-profiles.md|stackhawk-hawkscan-authz-profiles|HawkScan multi-role authorization scanning reference: detecting apps with multiple users/roles (RBAC signals, object-ownership queries, privileged routes), the credential cascade for building 2+ auth profiles (repo fixtures, data-seed multi-user, ask the user, degrade), why --all-plugins-per-profile is subtractive and requires plugins 422004/422005 in the resolved policy, the capability and provenance gates before passing the flag, the N-times scan-time warning, and reading per-profile attribution from evidence text. Use when an app has multiple roles and BOLA/BFLA coverage is wanted.||false"
  "api/skills/api/SKILL.md|stackhawk-api|Use when querying the StackHawk platform for security reporting, findings analysis, or app management. Triggers include \"stackhawk api\", \"security posture\", \"findings report\", \"show me findings\", \"untriaged findings\", \"which apps\", \"scan history\", \"security dashboard\", \"triage\", \"what needs attention\". Uses the combined hawk CLI (hawk op …) for all platform queries. Do NOT use for running scans (use the stackhawk-hawkscan rule for \"scan my app\", \"hawkscan\", \"stackhawk.yml\", \"DAST\") or for fixing/remediating code or vulnerabilities — this skill only reads and reports platform data.||false"
  "api/skills/api/references/hawk-op-shortcuts.md|stackhawk-api-hawk-op|hawk op shortcuts for the StackHawk API: user intent → single hawk op command mapping for scan drill-down, app/user/team/policy/repo/oas/config/secret/audit listing, hosted scan control, env management. All platform queries go through hawk op — no raw REST fallback.||false"
  "api/skills/api/references/reporting-recipes.md|stackhawk-api-recipes|StackHawk API reporting recipes: org security posture summary, app deep dive (scan -> alerts -> findings), stale apps detection, scan diff (what changed since last scan). Pre-built compositions using hawk op commands. Prefer hawk op shortcuts (stackhawk-api-hawk-op) for the deep-dive chain; use these recipes for the per-env untriaged posture view.||false"
  "hawkscan-ci/skills/hawkscan-ci/SKILL.md|stackhawk-hawkscan-ci|Use when the user wants to WIRE HawkScan into a CI/CD pipeline config file — triggers on \"set up hawkscan in CI\", \"add stackhawk to my pipeline\", \"scan in CI\", \"configure github actions / gitlab / jenkins / circleci for hawkscan\", \"wire hawkscan into ci/cd\". Provider-agnostic: detects the CI system, edits the pipeline file in place to add a HawkScan job, prompts for HAWK_API_KEY storage (CI-native secrets store or external secrets manager), wires commit-SHA + branch traceability. Defers all local-scan concerns (stackhawk.yml, auth, findings, triage) to stackhawk-hawkscan. If no local stackhawk.yml exists yet, still trigger and route local-config work to stackhawk-hawkscan. Do NOT trigger for documentation-only changes, informational/research questions about CI, or running a local scan (that is stackhawk-hawkscan) — this skill only edits CI pipeline config.|.github/workflows/**,.gitlab-ci.yml,Jenkinsfile*,.circleci/config.yml,azure-pipelines*.yml,bitbucket-pipelines.yml,.buildkite/pipeline.yml,.travis.yml,appspec.yml,buildspec.yml|false"
  "hawkscan-ci/skills/hawkscan-ci/references/execution-shapes.md|stackhawk-hawkscan-ci-execution-shapes|HawkScan CI execution shapes reference: native action (stackhawk/hawkscan-action) vs Docker image (stackhawk/hawkscan) vs CLI download; pinning strategy; per-provider quick-reference recipes for GitHub Actions, GitLab CI, Jenkins, CircleCI, Azure Pipelines, Bitbucket, Buildkite, Travis, AWS CodeBuild; SARIF / Code Scanning notes.||false"
  "hawkscan-ci/skills/hawkscan-ci/references/app-startup-patterns.md|stackhawk-hawkscan-ci-app-startup|HawkScan CI app-startup patterns reference: Docker Compose + wait-for-it, GitLab services keyword, GitHub Actions services map, build-then-run (Node, JVM), run-a-built-image, scan-existing-host (ephemeral env / preview deployment), networking gotchas (--network host vs host.docker.internal), health-check endpoint conventions.||false"
  "hawkscan-ci/skills/hawkscan-ci/references/failure-semantics.md|stackhawk-hawkscan-ci-failure|HawkScan CI failure semantics reference: exit codes 0/1/42, failureThreshold tuning, block-on-42 vs warn-only vs scheduled-baseline modes, retry strategy (don't retry 42), caching strategy (cache CLI/image, never findings), scheduled-vs-PR-trigger tradeoffs.||false"
  "stackhawk-data-seed/skills/stackhawk-data-seed/SKILL.md|stackhawk-data-seed|Use when the user says \"set up data for HawkScan\", \"my scan has no data to hit\", \"seed this repo for scanning\", or as a first-time-setup step before invoking hawkscan on a fresh repo. Drives the 'hawk perch seed' subcommands (preflight, validate, finalize): runs the static pre-flight, designs the minimum seed manifest from the repo digest, then validates and finalizes reviewed artifacts under data-seed/ (SQL / HTTP / gRPC / Mongo / shell scripts, a manifest.yaml, and a .data-seed-credentials.env handoff). Requires hawk 6.0.0 or newer; on older hawk it punts with an upgrade instruction. Does NOT write stackhawk.yml (hawkscan owns that). NOT autonomous — explicit user invocation only.|**/data-seed/manifest.yaml,**/.data-seed-credentials.env|false"
  "optimize/skills/optimize/SKILL.md|stackhawk-optimize|Use when the user asks to optimize, tune, or speed up a HawkScan scan, reduce false positives, or pick the right scan policy/plugins/tech flags for an app — or invokes /optimize. Analyzes the codebase, builds an isolated trial scan policy, runs one trial scan, and promotes or discards. Do NOT use for a normal scan or fixing vulns (use stackhawk-hawkscan) or for querying findings/posture (use stackhawk-api).||false"
  "optimize/skills/optimize/references/mapping.md|stackhawk-optimize-mapping|Optimize codebase-to-config mapping: tech-flag detection heuristics (reuses hawkscan's evidence-file detection), plugin selection from a base preset, stackhawk.yml correctness (app type, OpenAPI, GraphQL, auth), and the default-balanced speed-vs-coverage profile lean.||false"
  "optimize/skills/optimize/references/trial-lifecycle.md|stackhawk-optimize-trial|Optimize trial lifecycle: how a named scan policy reaches a scan via S3 download (non-destructive), deterministic OPTIMIZE_TRIAL_<APP>_<ENV> naming, crash-safe create/promote/discard sequences (orphan-policy and backup-file guards, reconstruct from the live policy), and failure handling.||false"
  "optimize/skills/optimize/references/cli-contract.md|stackhawk-optimize-cli|Optimize hawk op CLI contract: policy list/get/create/delete/assign and scan metrics commands the skill orchestrates, with flags and JSON output notes. The skill consumes these; it does not recompute metrics.||false"
  "optimize/skills/optimize/references/metrics-and-refine.md|stackhawk-optimize-metrics|Optimize post-scan metrics refine loop: MetricsJson schema (paths/operations/flags/health), flag-to-lever mapping (concurrency for rate-limited/timeout-prone; excludePaths for heavy/slow paths; auth for auth-wall), auto-vs-confirm tiers, concurrency step-down (halve from current, floor 1), and the capped refine loop.||false"
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
