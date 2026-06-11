#!/usr/bin/env bash
# Cursor stop hook for hawkscan plugin
# Fires when the agent loop ends. If code was modified but no scan was run,
# outputs followup_message to auto-trigger the agent to invoke the scan skill.

set -euo pipefail

# Only meaningful in a git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  exit 0
fi

# Cursor passes hook context via stdin as JSON
if [ ! -t 0 ]; then
  cat > /dev/null
fi

code_extensions="\.(java|kt|py|js|ts|tsx|jsx|go|rs|rb|php|cs|c|cpp|h|swift|scala|groovy|clj)$"

modified_code=""
modified_code=$(git diff --name-only HEAD 2>/dev/null | grep -E "$code_extensions" || true)
if [ -z "$modified_code" ]; then
  modified_code=$(git diff --cached --name-only 2>/dev/null | grep -E "$code_extensions" || true)
fi
if [ -z "$modified_code" ]; then
  modified_code=$(git log --since="1 hour ago" --name-only --pretty=format: 2>/dev/null | grep -E "$code_extensions" || true)
fi

if [ -z "$modified_code" ]; then
  exit 0
fi

# Check for scan evidence
scan_evidence="false"
if [ -f "findings.json" ] || [ -f "hawk_scan_output.json" ]; then
  scan_evidence="true"
fi
if git log --since="1 hour ago" --oneline 2>/dev/null | grep -i "scan\|hawkscan\|security fix\|vulnerability\|resolve CWE" >/dev/null 2>&1; then
  scan_evidence="true"
fi

if [ "$scan_evidence" = "true" ]; then
  exit 0
fi

file_count=$(echo "$modified_code" | sort -u | wc -l | tr -d ' ')

printf '{"followup_message": "Code files were modified (%d file(s)) but no HawkScan security scan was detected. Invoke the hawkscan skill now: configure stackhawk.yml if needed, run the scan, fix all findings, and rescan to verify."}\n' "$file_count"

exit 0
