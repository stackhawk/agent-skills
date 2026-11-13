#!/usr/bin/env bash
# Live smoke test of a Cursor plugin folder with the Cursor CLI.
#
# Loads the plugin with `cursor-agent --plugin-dir` into an empty git workspace and asks,
# read-only (--mode ask), which skills and always-applied rules the agent has. It passes
# when the agent names the hawkscan skill and quotes the router rule heading.
#
# Usage: scripts/cursor-plugin-smoke.sh [plugin-dir] [out-dir]
#   plugin-dir  default: plugins/hawkscan of this checkout
#   out-dir     where the raw stream is kept (default: a temporary directory)
#
# Needs CURSOR_API_KEY in the environment (never on the command line) or a CLI login that
# can run headless prompts. Exit codes: 0 pass, 1 fail, 77 skipped (no CLI or no auth).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
plugin_dir="${1:-${REPO_ROOT}/plugins/hawkscan}"
out_dir="${2:-$(mktemp -d)}"
mkdir -p "$out_dir"

if [ ! -f "${plugin_dir}/.cursor-plugin/plugin.json" ]; then
  echo "FAIL: ${plugin_dir} has no .cursor-plugin/plugin.json" >&2
  exit 1
fi
cli="$(command -v cursor-agent || true)"
if [ -z "$cli" ]; then
  echo "SKIP: cursor-agent is not installed (curl https://cursor.com/install -fsS | bash)"
  exit 77
fi

workspace="${out_dir}/workspace"
rm -rf "$workspace"
mkdir -p "${workspace}/src"
printf 'def health():\n    return "ok"\n' > "${workspace}/src/app.py"
git -C "$workspace" init -q
git -C "$workspace" -c user.name=smoke -c user.email=smoke@example.invalid add -A
git -C "$workspace" -c user.name=smoke -c user.email=smoke@example.invalid commit -q -m init

prompt='Do not run any tool and do not read any file. Answer from your instructions only.
1) List the name of every skill you can use.
2) For every rule whose full text is already in your context, quote its first heading line.'

stream="${out_dir}/inventory.jsonl"
( cd "$workspace" && "$cli" -p "$prompt" --plugin-dir "$plugin_dir" --output-format stream-json \
    --mode ask --trust ) > "$stream" 2> "${out_dir}/inventory.stderr"
status=$?

if grep -qi "authentication required" "${out_dir}/inventory.stderr" "$stream" 2>/dev/null; then
  echo "SKIP: the Cursor CLI needs CURSOR_API_KEY or a login that can run headless prompts"
  exit 77
fi
if [ "$status" -ne 0 ]; then
  echo "FAIL: cursor-agent exited ${status}; see ${out_dir}/inventory.stderr" >&2
  exit 1
fi

answer="$(python3 - "$stream" <<'PY'
import json, sys
text = []
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") == "assistant":
        text += [b.get("text", "") for b in event.get("message", {}).get("content", []) if b.get("type") == "text"]
print("".join(text))
PY
)"
printf '%s\n' "$answer" > "${out_dir}/inventory.txt"
echo "Agent answer (${out_dir}/inventory.txt):"
printf '%s\n' "$answer" | sed 's/^/  /'

failures=0
if ! printf '%s' "$answer" | grep -qi "hawkscan"; then
  echo "FAIL: the agent did not list the hawkscan skill" >&2
  failures=$((failures + 1))
fi
if ! printf '%s' "$answer" | grep -qi "StackHawk skills"; then
  echo "FAIL: the agent did not quote the always-applied router rule (# StackHawk skills)" >&2
  failures=$((failures + 1))
fi
if [ "$failures" -gt 0 ]; then
  exit 1
fi
echo "PASS: Cursor loaded the skill and the router rule from ${plugin_dir}"
