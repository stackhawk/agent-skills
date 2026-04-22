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
  "hawkscan/skills/hawkscan/references/config-patterns.md|stackhawk-hawkscan-config|stackhawk.yml configuration patterns: OpenAPI/REST, GraphQL, gRPC, SOAP, JSON-RPC API types. Spider and scan tuning, path scope control, auto policy, CSRF protection, header injection (replacer), multi-environment config, failure thresholds. For authentication, see stackhawk-hawkscan-auth.|**/stackhawk.yml,**/stackhawk-*.yml|false"
  "hawkscan/skills/hawkscan/references/auth/README.md|stackhawk-hawkscan-auth|stackhawk.yml authentication: strategy selection (usernamePassword, oauth, script, externalCommand, external), authorization types (cookieAuthorization, tokenAuthorization), testPath, loggedIn/loggedOut indicators, isJWT mode, common mistakes. Per-pattern details in references/auth/.|**/stackhawk.yml,**/stackhawk-*.yml|false"
  "hawkscan/skills/hawkscan/references/docker-usage.md|stackhawk-hawkscan-docker|HawkScan Docker usage: standard container run, scanning localhost apps, custom config files, environment variables, CI Docker environments, network configuration for host access.|**/Dockerfile*,**/docker-compose*|false"
  "hawkscan/skills/hawkscan/references/findings-and-fixes.md|stackhawk-hawkscan-findings|HawkScan findings reference: JSON output schema (--json-output), field reference, thresholdResult to exit code mapping, agentic fix task format, priority rules (severity, exploitability ordering), common findings quick reference (SQL injection, XSS, IDOR, path traversal, broken auth, information disclosure).||false"
  "hawkscan/skills/hawkscan/references/installation.md|stackhawk-hawkscan-install|HawkScan installation: Homebrew (macOS), package installers (all platforms), prerequisites (Java 17+), verification (hawk --version).||false"
  "hawkscan/skills/hawkscan/references/false-positives.md|stackhawk-hawkscan-false-positives|HawkScan false positives guide: identifying false positives, deciding fix vs suppress, excludePaths and failureThreshold config, excluding scan plugins, reporting accepted risk.||false"
  "api/skills/api/SKILL.md|stackhawk-api|Use when querying the StackHawk platform for security reporting, findings analysis, or app management. Triggers include \"stackhawk api\", \"security posture\", \"findings report\", \"show me findings\", \"untriaged findings\", \"which apps\", \"scan history\", \"security dashboard\", \"triage\", \"what needs attention\". Prefers the hawkop CLI when installed; falls back to raw REST calls otherwise. Do NOT use for scanning — use the stackhawk-hawkscan rule for \"scan my app\", \"hawkscan\", \"stackhawk.yml\", \"DAST\".||false"
  "api/skills/api/references/hawkop-shortcuts.md|stackhawk-api-hawkop|HawkOp CLI shortcuts for the StackHawk API: user intent → single hawkop command mapping for scan drill-down, app/user/team/policy/repo/oas/config/secret/audit listing, hosted scan control, env management. Replaces multi-step curl+jq pipelines. Use first when hawkop is installed; fall back to raw API (stackhawk-api-auth, stackhawk-api-endpoints) when hawkop doesn't wrap an endpoint.||false"
  "api/skills/api/references/api-auth.md|stackhawk-api-auth|StackHawk API authentication reference (fallback when hawkop is not installed): JWT token flow, HAWK_API_KEY setup, hawk_api and hawk_api_all_pages helper scripts, token refresh, V1/V2 pagination, 401/403 error diagnosis.||false"
  "api/skills/api/references/api-endpoints.md|stackhawk-api-endpoints|StackHawk API endpoint catalog (raw REST, used when hawkop doesn't wrap the endpoint): authentication, applications, environments, scan results drill-down chain (scans -> alerts -> findings -> evidence), organization-wide queries, teams, V1/V2 pagination patterns.||false"
  "api/skills/api/references/reporting-recipes.md|stackhawk-api-recipes|StackHawk API reporting recipes: org security posture summary, app deep dive (scan -> alerts -> findings), stale apps detection, scan diff (what changed since last scan). Pre-built jq compositions using hawk_api helpers. Prefer hawkop shortcuts (stackhawk-api-hawkop) for the deep-dive chain; use these recipes for the per-env untriaged posture view.||false"
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
