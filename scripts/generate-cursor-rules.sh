#!/usr/bin/env bash
set -euo pipefail

# ─── Cursor Rule Generation Script ───
# Transforms canonical SKILL.md + references/*.md into Cursor .mdc format.
# Run from repo root: bash scripts/generate-cursor-rules.sh
#
# Each entry in MAPPINGS defines:
#   source_file|output_name|cursor_description|globs (comma-separated, or empty)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/cursor/.cursor/rules"
PLUGINS_DIR="${REPO_ROOT}/plugins"

# ─── Frontmatter Mapping Config ───
# Format: source_path|output_name|description|globs
# Source paths are relative to PLUGINS_DIR
MAPPINGS=(
  "hawkscan/skills/hawkscan/SKILL.md|stackhawk-hawkscan|Use when configuring, running, or interpreting results from StackHawk's HawkScan DAST scanner. Triggers include \"hawkscan\", \"stackhawk\", \"stackhawk.yml\", \"hawk scan\", \"DAST\", \"dynamic security testing\", \"security scan\", \"scan my API/app\". Also trigger when a feature is being completed — phrases like \"feature complete\", \"finishing up feature\", \"ready for review\" should proactively suggest running a security scan.|**/stackhawk.yml,**/stackhawk-*.yml"
  "hawkscan/skills/hawkscan/references/cli-reference.md|stackhawk-hawkscan-cli|hawk CLI reference: scan commands and flags (--json-output, --verbose, --debug, --trace), validate commands (config, api, auth), perch daemon mode, diagnostic commands, exit codes, subcommand options for scan scope, scanner behavior, output artifacts, and git integration.|"
  "hawkscan/skills/hawkscan/references/config-patterns.md|stackhawk-hawkscan-config|stackhawk.yml configuration patterns: OpenAPI/REST, GraphQL, gRPC, SOAP, JSON-RPC API types. Authentication patterns: token/cookie injection, form login, OAuth2 (client credentials, password grant), external command, custom script. Spider and scan tuning, path scope control, auto policy, CSRF protection, header injection (replacer), multi-environment config, failure thresholds.|**/stackhawk.yml,**/stackhawk-*.yml"
  "hawkscan/skills/hawkscan/references/docker-usage.md|stackhawk-hawkscan-docker|HawkScan Docker usage: standard container run, scanning localhost apps, custom config files, environment variables, CI Docker environments, network configuration for host access.|**/Dockerfile*,**/docker-compose*"
  "hawkscan/skills/hawkscan/references/findings-and-fixes.md|stackhawk-hawkscan-findings|HawkScan findings reference: JSON output schema (--json-output), field reference, thresholdResult to exit code mapping, agentic fix task format, priority rules (severity, exploitability ordering), common findings quick reference (SQL injection, XSS, IDOR, path traversal, broken auth, information disclosure).|"
  "hawkscan/skills/hawkscan/references/installation.md|stackhawk-hawkscan-install|HawkScan installation: Homebrew (macOS), package installers (all platforms), prerequisites (Java 17+), verification (hawk --version).|"
  "api/skills/api/SKILL.md|stackhawk-api|Use when querying the StackHawk platform for security reporting, findings analysis, or app management. Triggers include \"stackhawk api\", \"security posture\", \"findings report\", \"show me findings\", \"untriaged findings\", \"which apps\", \"scan history\", \"security dashboard\", \"triage\", \"what needs attention\". Do NOT use for scanning — use the stackhawk-hawkscan rule for \"scan my app\", \"hawkscan\", \"stackhawk.yml\", \"DAST\".|"
  "api/skills/api/references/api-auth.md|stackhawk-api-auth|StackHawk API authentication reference: JWT token flow, HAWK_API_KEY setup, hawk_api and hawk_api_all_pages helper scripts, token refresh, V1/V2 pagination, 401/403 error diagnosis.|"
  "api/skills/api/references/api-endpoints.md|stackhawk-api-endpoints|StackHawk API endpoint catalog: REST endpoints for authentication, applications, environments, scan results drill-down chain (scans -> alerts -> findings -> evidence), organization-wide queries, teams, V1/V2 pagination patterns.|"
  "api/skills/api/references/reporting-recipes.md|stackhawk-api-recipes|StackHawk API reporting recipes: org security posture summary, app deep dive (scan -> alerts -> findings), stale apps detection, scan diff (what changed since last scan). Pre-built jq compositions using hawk_api helpers.|"
)

# ─── Generate ───

mkdir -p "${OUTPUT_DIR}"

# Clean old generated files
rm -f "${OUTPUT_DIR}"/*.mdc

error_count=0

for mapping in "${MAPPINGS[@]}"; do
  IFS='|' read -r source_path output_name description globs <<< "${mapping}"

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
alwaysApply: false
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
