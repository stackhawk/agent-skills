#!/usr/bin/env bash
# PostToolUse (Bash) nudge: after finishing-work git actions that touched skill material,
# suggest /benchmark once per session. Never blocks; never auto-launches.
set -euo pipefail
input="$(cat)"
cmd="$(printf '%s' "$input" | python3 -c 'import json,sys;print((json.load(sys.stdin).get("tool_input") or {}).get("command",""))' 2>/dev/null || true)"
case "$cmd" in
  *"git commit"*|*"gh pr create"*|*"git push"*) : ;;
  *) exit 0 ;;
esac
# changed files: injected for tests, else derived from git
if [ -n "${BENCHMARK_HOOK_CHANGED_FILES:-}" ]; then changed="$BENCHMARK_HOOK_CHANGED_FILES"
else changed="$(git diff --name-only origin/main...HEAD 2>/dev/null; git show --name-only --format= HEAD 2>/dev/null)"; fi
echo "$changed" | grep -qE 'plugins/.+/SKILL\.md|plugins/.+/references/|\.claude/skills/' || exit 0
marker_dir="${BENCHMARK_HOOK_MARKER_DIR:-${TMPDIR:-/tmp}}"
# de-dupe per session: PPID groups a session's tool calls
marker="$marker_dir/.benchmark-nudged-${PPID:-session}"
[ -f "$marker" ] && exit 0
: > "$marker"
msg="You just finished a change to agent-skills that touched skill files. Consider proving it works: ask the user if they want to run /benchmark <describe the change and the problem it should solve>. Example: /benchmark prove the app-discovery update makes agents explore thoroughly and land on correct app details. Do NOT run it automatically — offer it."
python3 -c 'import json,sys;print(json.dumps({"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":sys.argv[1]}}))' "$msg"
exit 0
