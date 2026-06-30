#!/usr/bin/env bash
set -euo pipefail

# ─── Install Script ───
# Copies StackHawk agent skills into a target project for platforms that
# require manual installation (Cursor, Copilot).
#
# Usage:
#   ./scripts/install.sh --platform cursor  --target /path/to/project
#   ./scripts/install.sh --platform copilot --target /path/to/project

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "Usage: $0 --platform <cursor|copilot> --target <project-path>" >&2
  echo "" >&2
  echo "Options:" >&2
  echo "  --platform  Platform to install for (cursor or copilot)" >&2
  echo "  --target    Path to the target project directory" >&2
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

case "$platform" in
  cursor)
    rules_dest="${target}/.cursor/rules"
    rules_source="${REPO_ROOT}/cursor/.cursor/rules"
    skills_dest="${target}/.cursor/skills"
    hooks_dest="${target}/.cursor/hooks"
    plugins_source="${REPO_ROOT}/plugins"
    cursor_hooks_source="${REPO_ROOT}/plugins/hawkscan/hooks/cursor"

    if [ ! -d "$rules_source" ]; then
      echo "ERROR: Cursor rules not found. Run 'bash scripts/generate-cursor-rules.sh' first." >&2
      exit 1
    fi

    # Check for existing StackHawk artifacts
    existing=()
    [ -d "$rules_dest" ] && ls "$rules_dest"/stackhawk-*.mdc >/dev/null 2>&1 && existing+=("rules")
    [ -d "$skills_dest/hawkscan" ] && existing+=("skills")
    [ -f "${target}/.cursor/hooks.json" ] && existing+=("hooks")

    if [ ${#existing[@]} -gt 0 ]; then
      echo "WARNING: StackHawk Cursor artifacts already exist: ${existing[*]}"
      echo ""
      read -rp "Overwrite? [y/N] " confirm
      if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
      fi
    fi

    # Rules
    mkdir -p "$rules_dest"
    cp "$rules_source"/stackhawk-*.mdc "$rules_dest/"
    count=$(ls "$rules_dest"/stackhawk-*.mdc 2>/dev/null | wc -l | tr -d ' ')
    echo "Installed ${count} Cursor rules to ${rules_dest}/"

    # Skills
    mkdir -p \
      "${skills_dest}/hawkscan" \
      "${skills_dest}/api" \
      "${skills_dest}/hawkscan-ci" \
      "${skills_dest}/stackhawk-data-seed" \
      "${skills_dest}/optimize"
    cp -r "${plugins_source}/hawkscan/skills/hawkscan/"* "${skills_dest}/hawkscan/"
    cp -r "${plugins_source}/api/skills/api/"* "${skills_dest}/api/"
    cp -r "${plugins_source}/hawkscan-ci/skills/hawkscan-ci/"* "${skills_dest}/hawkscan-ci/"
    cp -r "${plugins_source}/stackhawk-data-seed/skills/stackhawk-data-seed/"* "${skills_dest}/stackhawk-data-seed/"
    cp -r "${plugins_source}/optimize/skills/optimize/"* "${skills_dest}/optimize/"
    echo "Installed 5 Cursor skills to ${skills_dest}/"
    echo "  hawkscan/            — DAST scanning skill"
    echo "  api/                 — StackHawk API reporting skill"
    echo "  hawkscan-ci/         — CI/CD pipeline skill"
    echo "  stackhawk-data-seed/ — Data seed skill"
    echo "  optimize/            — Scan optimization skill"

    # Hooks
    mkdir -p "$hooks_dest"
    cp "${cursor_hooks_source}/hooks.json" "${target}/.cursor/hooks.json"
    cp "${cursor_hooks_source}/stop.sh" "${hooks_dest}/stop.sh"
    chmod +x "${hooks_dest}/stop.sh"
    echo "Installed Cursor hooks to ${target}/.cursor/"
    echo "  hooks.json           — hook configuration"
    echo "  hooks/stop.sh        — scan reminder on session end"
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
