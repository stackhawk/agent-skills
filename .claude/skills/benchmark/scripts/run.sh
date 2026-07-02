#!/usr/bin/env bash
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; export SCRIPTS_DIR
export AGENT_SKILLS_REPO="${AGENT_SKILLS_REPO:-/Users/brandon.ward/Code/agent-skills}"
export SKILL_SUBPATH="${SKILL_SUBPATH:-plugins/hawkscan/skills/hawkscan}"
OLD_REF="${OLD_REF:?set OLD_REF}"; NEW_REF="${NEW_REF:-origin/main}"
PROFILE="${PROFILE:-readonly}"; GRADER="${GRADER:-observational}"
MODEL="${MODEL:-claude-sonnet-5}"; JUDGE_MODEL="${JUDGE_MODEL:-claude-opus-4-8}"
BENCH_DIR="${BENCH_DIR:?set BENCH_DIR (holds apps.tsv, prompt.txt, ground-truth/)}"
CRED_ENV="${CRED_ENV:-}"    # space-separated env var names to pass through (e.g. "HAWK_API_KEY")
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
source "$SCRIPTS_DIR/harness.sh"

TS="$(date +%Y%m%d-%H%M%S)"; RUN="$BENCH_DIR/runs/$TS"; mkdir -p "$RUN/cells"
PROMPT="$(cat "$BENCH_DIR/prompt.txt")"
echo "== benchmark $TS  profile=$PROFILE grader=$GRADER model=$MODEL old=$OLD_REF new=$NEW_REF =="
if [ "$DRY" = 0 ]; then
  materialize_skill "$OLD_REF" "$SCRIPTS_DIR/../.skills/old"
  materialize_skill "$NEW_REF" "$SCRIPTS_DIR/../.skills/new"
fi
while IFS=$'\t' read -r app url pin; do
  [ -z "$app" ] && continue
  for arm in old new; do
    cell="$RUN/cells/${arm}__${app}"; mkdir -p "$cell"
    echo "-- cell ${arm}__${app} ($url @ $pin)"
    [ "$DRY" = 1 ] && continue
    git clone --depth 1 --branch "$pin" "$url" "$cell/workdir" >/dev/null 2>&1 \
      || git clone --depth 1 "$url" "$cell/workdir" >/dev/null 2>&1 \
      || { echo "clone failed ${arm}__${app}" >&2; echo clone_failed > "$cell/error"; continue; }
    build_config_dir "$SCRIPTS_DIR/../.skills/$arm" "$MODEL" "$cell/config" "$PROFILE" "$cell/workdir" \
      || { echo "config failed ${arm}__${app}" >&2; echo config_failed > "$cell/error"; continue; }
    # pass through only the named credential envs
    credflags=(); for v in $CRED_ENV; do credflags+=("$v=${!v:-}"); done
    set +e
    ( cd "$cell/workdir" && env "${credflags[@]}" \
      CLAUDE_CONFIG_DIR="$cell/config" BASH_DEFAULT_TIMEOUT_MS=2700000 BASH_MAX_TIMEOUT_MS=3600000 \
      claude --print --verbose --output-format stream-json \
        --permission-mode bypassPermissions --model "$MODEL" "$PROMPT" \
        > "$cell/transcript.jsonl" 2> "$cell/agent.stderr" )
    echo "$?" > "$cell/exit_code"
    set -e
    git -C "$cell/workdir" diff > "$cell/fix.diff" 2>/dev/null || true
    grep -i "Denied (benchmark guard" "$cell/transcript.jsonl" "$cell/agent.stderr" > "$cell/guard-denies.txt" 2>/dev/null || true
    python3 "$SCRIPTS_DIR/grade.py" --cell "$cell" --app "$app" \
      --ground-truth "$BENCH_DIR/ground-truth/$app.json" --grader "$GRADER" --judge-model "$JUDGE_MODEL" \
      || echo "grade failed ${arm}__${app}" >&2
  done
done < "$BENCH_DIR/apps.tsv"
[ "$DRY" = 1 ] && { echo "(dry run — no cells executed)"; exit 0; }
python3 "$SCRIPTS_DIR/report.py" --run "$RUN"
echo "DONE: $RUN/report.md"
