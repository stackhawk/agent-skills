#!/usr/bin/env bash
# Live smoke test of a Cursor plugin folder with the Cursor CLI.
#
# Asks the agent, read-only (--mode ask), which skills it can use: once with the plugin
# (`cursor-agent --plugin-dir`) and once without it, as a control, in an empty git workspace.
# It passes when the agent lists every skill that the plugin ships and the control does not
# list at least one of them. An account can already have StackHawk skills (for example from
# a Cursor team marketplace); when the control lists all of them, the result is inconclusive.
#
# It does not check rules or hooks. Cursor CLI 2026.11.11 loads the skills of a plugin but
# does not put plugin rules in the context of a headless prompt, and it runs stop hooks only
# in interactive sessions.
#
# Usage: scripts/cursor-plugin-smoke.sh [plugin-dir] [out-dir]
#   plugin-dir  default: plugins/hawkscan of this checkout
#   out-dir     where the raw streams are kept (default: a temporary directory)
#
# Needs CURSOR_API_KEY in the environment (never on the command line) or a CLI login that
# can run headless prompts. Exit codes: 0 pass, 1 fail, 77 skipped (no CLI, no auth, or a
# control that already lists every skill of the plugin).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
plugin_dir="${1:-${REPO_ROOT}/plugins/hawkscan}"
out_dir="${2:-$(mktemp -d)}"
mkdir -p "$out_dir"

if [ ! -f "${plugin_dir}/.cursor-plugin/plugin.json" ]; then
  echo "FAIL: ${plugin_dir} has no .cursor-plugin/plugin.json" >&2
  exit 1
fi
# The CLI runs inside the workspace, so a relative plugin path would not resolve there.
plugin_dir="$(cd "$plugin_dir" && pwd)"
cli="$(command -v cursor-agent || true)"
if [ -z "$cli" ]; then
  echo "SKIP: cursor-agent is not installed (curl https://cursor.com/install -fsS | bash)"
  exit 77
fi

# The skill names the plugin ships: the `name:` of each SKILL.md under the manifest's
# `skills` path (default: skills/).
expected="$(python3 - "$plugin_dir" <<'PY'
import json, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
paths = json.loads((root / ".cursor-plugin" / "plugin.json").read_text()).get("skills", "./skills/")
for path in paths if isinstance(paths, list) else [paths]:
    for skill in sorted((root / path).glob("*/SKILL.md")):
        match = re.search(r"^name:\s*['\"]?([^'\"\s]+)", skill.read_text(), re.M)
        if match:
            print(match.group(1))
PY
)"
if [ -z "$expected" ]; then
  echo "FAIL: ${plugin_dir} ships no skill with a name" >&2
  exit 1
fi

workspace="${out_dir}/workspace"
rm -rf "$workspace"
mkdir -p "${workspace}/src"
printf 'def health():\n    return "ok"\n' > "${workspace}/src/app.py"
git -C "$workspace" init -q
git -C "$workspace" -c user.name=smoke -c user.email=smoke@example.invalid add -A
git -C "$workspace" -c user.name=smoke -c user.email=smoke@example.invalid commit -q -m init

prompt='Do not run any tool and do not read any file. Answer from your instructions only.
List the name of every skill you can use, one per line, in the form "SKILL: <name>". Write nothing else.'

# ask <label> [cli args...]: runs the prompt and writes the skill names to <label>.txt.
# Returns 77 when the CLI has no usable authentication, 1 when it fails.
ask() {
  local label="$1"
  shift
  local stream="${out_dir}/${label}.jsonl"
  ( cd "$workspace" && "$cli" -p "$prompt" "$@" --output-format stream-json --mode ask --trust ) \
    > "$stream" 2> "${out_dir}/${label}.stderr"
  local status=$?
  if grep -qi "authentication required" "${out_dir}/${label}.stderr" "$stream" 2>/dev/null; then
    return 77
  fi
  if [ "$status" -ne 0 ]; then
    echo "FAIL: cursor-agent exited ${status} (${label}); see ${out_dir}/${label}.stderr" >&2
    return 1
  fi
  python3 - "$stream" > "${out_dir}/${label}.txt" <<'PY'
import json, re, sys
text = []
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") == "assistant":
        text += [b.get("text", "") for b in event.get("message", {}).get("content", []) if b.get("type") == "text"]
for match in re.finditer(r"SKILL:\s*`?([^`\s]+)", "".join(text)):
    print(match.group(1).split(":")[-1].lower())
PY
}

stop_unless_ok() {
  if [ "$1" -eq 77 ]; then
    echo "SKIP: the Cursor CLI needs CURSOR_API_KEY or a login that can run headless prompts"
    exit 77
  elif [ "$1" -ne 0 ]; then
    exit 1
  fi
}
ask plugin --plugin-dir "$plugin_dir"
stop_unless_ok $?
ask control
stop_unless_ok $?

echo "Skills the plugin ships: $(echo "$expected" | tr '\n' ' ')"
echo "Listed with the plugin:  $(tr '\n' ' ' < "${out_dir}/plugin.txt")"
echo "Listed without it:       $(tr '\n' ' ' < "${out_dir}/control.txt")"

missing="" proven=""
for name in $expected; do
  lower="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
  grep -qxF "$lower" "${out_dir}/plugin.txt" || missing="${missing} ${name}"
  grep -qxF "$lower" "${out_dir}/control.txt" || proven="${proven} ${name}"
done
if [ -n "$missing" ]; then
  echo "FAIL: the agent did not list these skills of the plugin:${missing}" >&2
  exit 1
fi
if [ -z "$proven" ]; then
  echo "SKIP: the control already lists every skill of the plugin, so the plugin's part cannot be shown." \
    "Use an account without StackHawk plugins (for example from a team marketplace)."
  exit 77
fi
echo "PASS: Cursor loaded the plugin's skills from ${plugin_dir} (absent without it:${proven})"
