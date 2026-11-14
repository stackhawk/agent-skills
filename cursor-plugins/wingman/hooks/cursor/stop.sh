#!/usr/bin/env bash
# Cursor stop hook for hawkscan plugin
# Fires when the agent loop ends. If the turn ended normally, code is modified and no
# scan ran, it prints one followup_message, which Cursor submits as the next user message.
#
# It stays silent unless all of these are true:
#   - the payload status is "completed" (not "aborted" or "error")
#   - loop_count is 0 (this turn is not itself a hook follow-up)
#   - the working tree or the index holds a code change (new untracked files count)
#   - there is no scan evidence
#   - it has not already asked in this conversation
# Unreadable input means silence. The hook entry also sets "loop_limit": 1.
#
# Cursor resets loop_count to 0 on every user message, so the hook records each
# conversation it asked in (a hash of conversation_id, one line each, in
# $(git rev-parse --git-path stackhawk/cursor-stop-asked); not in git status) and asks
# once per conversation. Without a conversation_id it does not record anything.
#
# Cursor runs user-level hooks from ~/.cursor/ and plugin stop hooks from the workspace
# root, so the project directory comes from CURSOR_PROJECT_DIR, then from the payload's
# workspace_roots[0], then from the working directory.

set -euo pipefail

payload=""
if [ ! -t 0 ]; then
  payload="$(cat)"
fi

# Prints one top-level field of the payload, or nothing. jq when present; otherwise a
# pattern match on the one-line JSON that Cursor sends.
field() {
  local name="$1"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$payload" | jq -r --arg k "$name" \
      'if type == "object" then (.[$k] | if type == "string" or type == "number" then tostring else empty end) else empty end' \
      2>/dev/null || true
    return
  fi
  local flat
  flat="$(printf '%s' "$payload" | tr -d '\n\r')"
  case "$name" in
    status) printf '%s' "$flat" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([a-z_]*\)".*/\1/p' ;;
    loop_count) printf '%s' "$flat" | sed -n 's/.*"loop_count"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' ;;
    conversation_id) printf '%s' "$flat" | sed -n 's/.*"conversation_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' ;;
  esac
}

first_workspace_root() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$payload" | jq -r '.workspace_roots[0]? // empty | strings' 2>/dev/null || true
    return
  fi
  printf '%s' "$payload" | tr -d '\n\r' |
    sed -n 's/.*"workspace_roots"[[:space:]]*:[[:space:]]*\[[[:space:]]*"\([^"]*\)".*/\1/p'
}

status="$(field status)"
loop_count="$(field loop_count)"
if [ "$status" != "completed" ] || [ "$loop_count" != "0" ]; then
  exit 0
fi

project_dir="${CURSOR_PROJECT_DIR:-}"
if [ -z "$project_dir" ] || [ ! -d "$project_dir" ]; then
  project_dir="$(first_workspace_root)"
fi
if [ -n "$project_dir" ] && [ -d "$project_dir" ]; then
  cd "$project_dir"
fi

# Only meaningful in a git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  exit 0
fi

code_extensions="\.(java|kt|py|js|ts|tsx|jsx|go|rs|rb|php|cs|c|cpp|h|swift|scala|groovy|clj)$"

# Uncommitted changes only: a commit is not evidence of a change made in this turn.
# New files count too (untracked and not ignored), so a turn that only adds code fires.
modified_code="$( {
    git diff --name-only HEAD 2>/dev/null || true
    git diff --cached --name-only 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | grep -E "$code_extensions" | sort -u || true)"
if [ -z "$modified_code" ]; then
  exit 0
fi

# Check for scan evidence
if [ -f "findings.json" ] || [ -f "hawk_scan_output.json" ]; then
  exit 0
fi
if git log --since="1 hour ago" --oneline 2>/dev/null | grep -i "scan\|hawkscan\|security fix\|vulnerability\|resolve CWE" >/dev/null 2>&1; then
  exit 0
fi

# One follow-up per conversation. Record before printing; a failed write still prints.
conversation_id="$(field conversation_id)"
if [ -n "$conversation_id" ]; then
  key="$(printf '%s' "$conversation_id" | git hash-object --stdin 2>/dev/null || true)"
  record="$(git rev-parse --git-path stackhawk/cursor-stop-asked 2>/dev/null || true)"
  if [ -n "$key" ] && [ -n "$record" ]; then
    if [ -f "$record" ] && grep -Fxq "$key" "$record" 2>/dev/null; then
      exit 0
    fi
    {
      mkdir -p "$(dirname "$record")" &&
        printf '%s\n' "$key" >> "$record" &&
        tail -n 200 "$record" > "${record}.tmp" &&
        mv "${record}.tmp" "$record"
    } 2>/dev/null || true
  fi
fi

file_count=$(printf '%s\n' "$modified_code" | wc -l | tr -d ' ')

printf '{"followup_message": "Code files were modified (%d file(s)) but no HawkScan security scan was detected. Invoke the hawkscan skill now: configure stackhawk.yml if needed, run the scan, fix all findings, and rescan to verify."}\n' "$file_count"

exit 0
