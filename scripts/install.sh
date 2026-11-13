#!/usr/bin/env bash
set -euo pipefail

# ─── Install Script ───
# Copies StackHawk agent skills into a target project for platforms that
# require manual installation (Cursor, Copilot).
#
# Usage:
#   ./scripts/install.sh --platform cursor  --target /path/to/project
#   ./scripts/install.sh --platform cursor  --target ~        # user level: skills and stop hook
#   ./scripts/install.sh --platform copilot --target /path/to/project

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "Usage: $0 --platform <cursor|copilot> --target <project-path>" >&2
  echo "" >&2
  echo "Options:" >&2
  echo "  --platform  Platform to install for (cursor or copilot)" >&2
  echo "  --target    Path to the target project directory (for cursor, your home" >&2
  echo "              directory gives a user-level install: skills and the stop hook)" >&2
  exit 1
}

platform=""
target=""

while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --target)   target="$2";   shift 2 ;;
    *)          usage ;;
  esac
done

if [ -z "$platform" ] || [ -z "$target" ]; then
  usage
fi

if [ ! -d "$target" ]; then
  echo "ERROR: Target directory does not exist: ${target}" >&2
  exit 1
fi

# ─── Cursor ───
# Project install: the five skills in .cursor/skills/, the router and stackhawk.yml
# pointer rules in .cursor/rules/, .cursor/hooks/stackhawk-stop.sh, and one stop entry
# merged into .cursor/hooks.json.
# User-level install (--target is your home directory): the skills and the stop hook
# only. Cursor has no file-based user rules, and it runs user hooks from ~/.cursor/, so
# the hook command there is ./hooks/stackhawk-stop.sh.
# The installer replaces only files it owns: the five StackHawk skill folders, the two
# rules, the hook script, and its own hooks.json entry. It also removes what older
# versions installed: the 28 rules in scripts/cursor-legacy-rules.txt and a
# .cursor/hooks/stop.sh that it wrote. Other rules, skills and hooks stay.

CURSOR_SKILLS=(
  "hawkscan|plugins/hawkscan/skills/hawkscan|DAST scanning skill"
  "api|plugins/api/skills/api|StackHawk API reporting skill"
  "hawkscan-ci|plugins/hawkscan-ci/skills/hawkscan-ci|CI/CD pipeline skill"
  "stackhawk-data-seed|plugins/stackhawk-data-seed/skills/stackhawk-data-seed|Data seed skill"
  "optimize|plugins/optimize/skills/optimize|Scan optimization skill"
)
CURSOR_RULES_SOURCE="${REPO_ROOT}/plugins/hawkscan/rules"
CURSOR_HOOKS_SOURCE="${REPO_ROOT}/plugins/hawkscan/hooks/cursor"
CURSOR_LEGACY_RULES="${REPO_ROOT}/scripts/cursor-legacy-rules.txt"
CURSOR_HOOK_SCRIPT="stackhawk-stop.sh"
CURSOR_LEGACY_HOOK_MARKER="# Cursor stop hook for hawkscan plugin"
CURSOR_PROJECT_COMMAND=".cursor/hooks/${CURSOR_HOOK_SCRIPT}"
CURSOR_USER_COMMAND="./hooks/${CURSOR_HOOK_SCRIPT}"

have_python() {
  command -v python3 >/dev/null 2>&1
}

# Prints an error and exits 1 if hooks.json cannot be merged. Never writes.
cursor_validate_hooks_json() {
  local file="$1"
  [ -f "$file" ] || return 0
  have_python || return 0
  local problem
  problem="$(python3 - "$file" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception as error:
    print(f"it is not valid JSON ({error})")
    sys.exit(0)
if not isinstance(data, dict):
    print("its top level is not an object")
elif not isinstance(data.get("hooks", {}), dict):
    print('its "hooks" value is not an object')
elif not isinstance(data.get("hooks", {}).get("stop", []), list):
    print('its "hooks"."stop" value is not a list')
PY
)"
  if [ -n "$problem" ]; then
    echo "ERROR: ${file} cannot be updated: ${problem}." >&2
    echo "Nothing was installed. Fix the file, then run the installer again." >&2
    exit 1
  fi
}

# A folder in a skills directory is ours when its SKILL.md has our name and is a StackHawk skill.
cursor_is_stackhawk_skill() {
  local dir="$1" name="$2" found
  [ -f "${dir}/SKILL.md" ] || return 1
  found="$(grep -m1 '^name:' "${dir}/SKILL.md" | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')"
  [ "$found" = "$name" ] && grep -qi 'stackhawk\|hawkscan' "${dir}/SKILL.md"
}

cursor_preflight() {
  local dot_cursor="$1" entry name
  for entry in "${CURSOR_SKILLS[@]}"; do
    name="${entry%%|*}"
    if [ -e "${dot_cursor}/skills/${name}" ] && ! cursor_is_stackhawk_skill "${dot_cursor}/skills/${name}" "$name"; then
      echo "ERROR: ${dot_cursor}/skills/${name} exists and is not the StackHawk ${name} skill." >&2
      echo "Nothing was installed. Move that folder away, then run the installer again." >&2
      exit 1
    fi
  done
  cursor_validate_hooks_json "${dot_cursor}/hooks.json"
}

cursor_install_skills() {
  local dot_cursor="$1" entry name rest src
  mkdir -p "${dot_cursor}/skills"
  for entry in "${CURSOR_SKILLS[@]}"; do
    name="${entry%%|*}"; rest="${entry#*|}"; src="${REPO_ROOT}/${rest%%|*}"
    rm -rf "${dot_cursor}/skills/${name}"
    mkdir -p "${dot_cursor}/skills/${name}"
    cp -R "${src}/." "${dot_cursor}/skills/${name}/"
  done
  echo "Installed ${#CURSOR_SKILLS[@]} Cursor skills to ${dot_cursor}/skills/"
  for entry in "${CURSOR_SKILLS[@]}"; do
    name="${entry%%|*}"
    printf '  %-24s - %s\n' "${name}/" "${entry##*|}"
  done
}

# Removes the rules older installers wrote. Prints how many it removed.
cursor_remove_legacy_rules() {
  local rules_dir="$1" removed=0 name
  [ -d "$rules_dir" ] || { echo 0; return; }
  while IFS= read -r name; do
    case "$name" in ''|'#'*) continue ;; esac
    if [ -f "${rules_dir}/${name}" ]; then
      rm -f "${rules_dir}/${name}"
      removed=$((removed + 1))
    fi
  done < "$CURSOR_LEGACY_RULES"
  echo "$removed"
}

cursor_install_rules() {
  local dot_cursor="$1" scope="$2" removed
  removed="$(cursor_remove_legacy_rules "${dot_cursor}/rules")"
  if [ "$scope" = "project" ]; then
    mkdir -p "${dot_cursor}/rules"
    cp "${CURSOR_RULES_SOURCE}"/*.mdc "${dot_cursor}/rules/"
    echo "Installed 2 Cursor rules to ${dot_cursor}/rules/"
    echo "  stackhawk.mdc            - always-applied router (names the skills and when each applies)"
    echo "  stackhawk-config.mdc     - applies while stackhawk.yml is in context"
  else
    echo "No rules installed: Cursor has no file-based user rules. For the router rule, run a"
    echo "project install or install the hawkscan plugin."
  fi
  if [ "$removed" -gt 0 ]; then
    echo ""
    echo "WARNING: Removed ${removed} legacy StackHawk rules from ${dot_cursor}/rules/."
    echo "  The generated rules in cursor/.cursor/rules/ are deprecated and are no longer installed:"
    echo "  Cursor now loads the skills on demand and reads one small router rule."
    echo "  cursor/ will be removed in the next major release."
  fi
}

cursor_write_fresh_hooks_json() {
  local file="$1" command="$2"
  sed "s#${CURSOR_PROJECT_COMMAND}#${command}#" "${CURSOR_HOOKS_SOURCE}/hooks.json" > "$file"
}

cursor_merge_hooks_json() {
  local file="$1" command="$2" drop_legacy="$3"
  python3 - "$file" "$command" "${CURSOR_HOOKS_SOURCE}/hooks.json" "$drop_legacy" <<'PY'
import json, sys
path, command, template, drop_legacy = sys.argv[1:5]
with open(template) as f:
    entry = dict(json.load(f)["hooks"]["stop"][0], command=command)
with open(path) as f:
    data = json.load(f)
if "version" not in data:
    data = {"version": 1, **data}
hooks = data.setdefault("hooks", {})

def ours(item):
    if not isinstance(item, dict):
        return False
    cmd = str(item.get("command", "")).strip("\"' ")
    return cmd.endswith("stackhawk-stop.sh") or (drop_legacy == "1" and cmd == ".cursor/hooks/stop.sh")

hooks["stop"] = [item for item in hooks.get("stop", []) if not ours(item)] + [entry]
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

cursor_install_hook() {
  local dot_cursor="$1" scope="$2" command legacy="${1}/hooks/stop.sh" drop_legacy=0
  command="$CURSOR_PROJECT_COMMAND"
  [ "$scope" = "user" ] && command="$CURSOR_USER_COMMAND"
  mkdir -p "${dot_cursor}/hooks"
  cp "${CURSOR_HOOKS_SOURCE}/stop.sh" "${dot_cursor}/hooks/${CURSOR_HOOK_SCRIPT}"
  chmod +x "${dot_cursor}/hooks/${CURSOR_HOOK_SCRIPT}"
  if [ -f "$legacy" ] && grep -qF "$CURSOR_LEGACY_HOOK_MARKER" "$legacy"; then
    drop_legacy=1
  fi

  if [ ! -f "${dot_cursor}/hooks.json" ]; then
    cursor_write_fresh_hooks_json "${dot_cursor}/hooks.json" "$command"
  elif have_python; then
    cursor_merge_hooks_json "${dot_cursor}/hooks.json" "$command" "$drop_legacy"
  else
    echo "WARNING: python3 was not found, so ${dot_cursor}/hooks.json was not changed."
    echo "  Add this entry to its \"hooks\".\"stop\" list:"
    echo "    {\"command\": \"${command}\", \"loop_limit\": 1}"
    if [ "$drop_legacy" = 1 ]; then
      echo "  Then remove the entry for .cursor/hooks/stop.sh and delete ${legacy}."
    fi
    return
  fi
  if [ "$drop_legacy" = 1 ]; then
    rm -f "$legacy"
    echo "Removed the old StackHawk hook ${legacy} and its hooks.json entry."
  fi
  echo "Installed the Cursor stop hook to ${dot_cursor}/"
  echo "  hooks/${CURSOR_HOOK_SCRIPT}  - asks for one scan after a turn that changed code without one"
  echo "  hooks.json               - one stop entry (${command}); other entries are kept"
}

install_cursor() {
  local dot_cursor="${target%/}/.cursor" scope="project" target_physical home_physical
  target_physical="$(cd "$target" && pwd -P)"
  home_physical="$(cd "${HOME:-/nonexistent}" 2>/dev/null && pwd -P || true)"
  if [ -n "$home_physical" ] && [ "$target_physical" = "$home_physical" ]; then
    scope="user"
  fi

  for f in "$CURSOR_LEGACY_RULES" "${CURSOR_HOOKS_SOURCE}/stop.sh" "${CURSOR_HOOKS_SOURCE}/hooks.json"; do
    if [ ! -f "$f" ]; then
      echo "ERROR: ${f} not found. Is the repository fully checked out?" >&2
      exit 1
    fi
  done

  cursor_preflight "$dot_cursor"
  echo "Installing StackHawk for Cursor (${scope} level) into ${dot_cursor}/"
  echo ""
  cursor_install_skills "$dot_cursor"
  cursor_install_rules "$dot_cursor" "$scope"
  cursor_install_hook "$dot_cursor" "$scope"
}

case "$platform" in
  cursor)
    install_cursor
    ;;

  copilot)
    dest="${target}/.agents/skills"
    source="${REPO_ROOT}/plugins"

    if [ -d "${dest}/hawkscan" ] || [ -d "${dest}/stackhawk-api" ]; then
      echo "WARNING: StackHawk skills already exist in ${dest}/"
      echo "Directories that will be overwritten:"
      [ -d "${dest}/hawkscan" ] && echo "  hawkscan/"
      [ -d "${dest}/stackhawk-api" ] && echo "  stackhawk-api/"
      echo ""
      read -rp "Overwrite? [y/N] " confirm
      if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
      fi
    fi

    mkdir -p "${dest}/hawkscan" "${dest}/stackhawk-api"
    cp -r "${source}/hawkscan/skills/hawkscan/"* "${dest}/hawkscan/"
    cp -r "${source}/api/skills/api/"* "${dest}/stackhawk-api/"
    echo "Installed StackHawk skills to ${dest}/"
    echo "  hawkscan/       — DAST scanning skill"
    echo "  stackhawk-api/  — API reporting skill"
    ;;

  *)
    echo "ERROR: Unknown platform '${platform}'. Use 'cursor' or 'copilot'." >&2
    exit 1
    ;;
esac
