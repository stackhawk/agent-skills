#!/usr/bin/env bash
# HawkScan app-discovery eval (single arm, pulse).
# Clones each real repo, runs the CURRENT hawkscan skill headless against it with a
# read-only guard, and grades the discovery output against the repo's answer key.
#
# Config via env:
#   MODEL         agent model (default claude-sonnet-5)
#   JUDGE_MODEL   skill-blind judge model (default claude-opus-4-8)
#   PASS_THRESHOLD  per-repo pass bar out of 12 (default 9; consumed by report.py)
#   NO_JUDGE=1    deterministic process-checks only (no ANTHROPIC_API_KEY needed)
# Auth: export CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY for the headless runs.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUITE_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SUITE_DIR/../.." && pwd)"
SKILL_SRC="$REPO_ROOT/plugins/hawkscan/skills/hawkscan"
MODEL="${MODEL:-claude-sonnet-5}"
JUDGE_MODEL="${JUDGE_MODEL:-claude-opus-4-8}"
NO_JUDGE_FLAG=""; [ "${NO_JUDGE:-0}" = "1" ] && NO_JUDGE_FLAG="--no-judge"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

test -f "$SKILL_SRC/SKILL.md" || { echo "no hawkscan SKILL.md at $SKILL_SRC" >&2; exit 1; }

TS="$(date +%Y%m%d-%H%M%S)"; RUN="$SUITE_DIR/runs/$TS"; mkdir -p "$RUN/cells"
PROMPT="$(cat "$SUITE_DIR/prompt.txt")"
echo "== discovery eval $TS  model=$MODEL judge=$JUDGE_MODEL dry=$DRY =="

build_config_dir() {  # <cell_config_dir>
  local cfg="$1"
  rm -rf "$cfg"; mkdir -p "$cfg/skills" "$cfg/hooks"
  cp -R "$SKILL_SRC" "$cfg/skills/hawkscan"
  cp "$SCRIPTS_DIR/guard.py" "$cfg/hooks/guard.py"
  python3 - "$MODEL" "$cfg" > "$cfg/settings.json" <<'PY'
import json, sys
model, cfg = sys.argv[1], sys.argv[2]
json.dump({
    "model": model,
    "enableAllProjectMcpServers": False,
    "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f"python3 {cfg}/hooks/guard.py"}]}]},
}, sys.stdout, indent=2)
PY
}

while IFS=$'\t' read -r app url pin; do
  [ -z "$app" ] && continue
  cell="$RUN/cells/$app"; mkdir -p "$cell"
  echo "-- cell $app ($url @ ${pin:0:12})"
  [ "$DRY" = 1 ] && continue
  git clone --depth 1 "$url" "$cell/workdir" >/dev/null 2>&1 \
    || { echo "clone failed: $app" >&2; echo clone_failed > "$cell/error"; continue; }
  if [ -n "$pin" ]; then
    git -C "$cell/workdir" fetch --depth 1 origin "$pin" >/dev/null 2>&1 \
      && git -C "$cell/workdir" checkout -q FETCH_HEAD 2>/dev/null || true
  fi
  build_config_dir "$cell/config" \
    || { echo "config-build failed: $app" >&2; echo config_failed > "$cell/error"; continue; }
  set +e
  # cwd MUST be the cloned app -- never the suite dir, which holds the answer keys.
  ( cd "$cell/workdir" && \
    CLAUDE_CONFIG_DIR="$cell/config" BASH_DEFAULT_TIMEOUT_MS=2700000 BASH_MAX_TIMEOUT_MS=3600000 \
    claude --print --verbose --output-format stream-json \
      --permission-mode bypassPermissions --model "$MODEL" "$PROMPT" \
      > "$cell/transcript.jsonl" 2> "$cell/agent.stderr" )
  echo "$?" > "$cell/exit_code"
  set -e
  grep -i "Denied (read-only" "$cell/transcript.jsonl" "$cell/agent.stderr" \
    > "$cell/guard-denies.txt" 2>/dev/null || true
  python3 "$SCRIPTS_DIR/grade.py" --cell "$cell" --app "$app" \
    --answer-key "$SUITE_DIR/answer-keys/$app.json" --judge-model "$JUDGE_MODEL" $NO_JUDGE_FLAG \
    || echo "grade failed for $app" >&2
done < "$SUITE_DIR/apps.tsv"

[ "$DRY" = 1 ] && { echo "(dry run -- listed cells, executed nothing)"; exit 0; }
python3 "$SCRIPTS_DIR/report.py" --run "$RUN"
echo "DONE: $RUN/report.md"
