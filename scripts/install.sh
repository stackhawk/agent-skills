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
    dest="${target}/.cursor/rules"
    source="${REPO_ROOT}/cursor/.cursor/rules"

    if [ ! -d "$source" ]; then
      echo "ERROR: Cursor rules not found. Run 'bash scripts/generate-cursor-rules.sh' first." >&2
      exit 1
    fi

    if [ -d "$dest" ] && ls "$dest"/stackhawk-*.mdc >/dev/null 2>&1; then
      echo "WARNING: StackHawk Cursor rules already exist in ${dest}/"
      echo "Files that will be overwritten:"
      ls "$dest"/stackhawk-*.mdc 2>/dev/null | while read -r f; do echo "  $(basename "$f")"; done
      echo ""
      read -rp "Overwrite? [y/N] " confirm
      if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
      fi
    fi

    mkdir -p "$dest"
    cp "$source"/stackhawk-*.mdc "$dest/"
    count=$(ls "$dest"/stackhawk-*.mdc 2>/dev/null | wc -l | tr -d ' ')
    echo "Installed ${count} Cursor rules to ${dest}/"
    ;;

  copilot)
    dest="${target}/.agents/skills"
    source="${REPO_ROOT}/plugins"

    if [ -d "${dest}/hawkscan" ] || [ -d "${dest}/api" ]; then
      echo "WARNING: StackHawk skills already exist in ${dest}/"
      echo "Directories that will be overwritten:"
      [ -d "${dest}/hawkscan" ] && echo "  hawkscan/"
      [ -d "${dest}/api" ] && echo "  api/"
      echo ""
      read -rp "Overwrite? [y/N] " confirm
      if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
      fi
    fi

    mkdir -p "${dest}/hawkscan" "${dest}/api"
    cp -r "${source}/hawkscan/skills/hawkscan/"* "${dest}/hawkscan/"
    cp -r "${source}/api/skills/api/"* "${dest}/api/"
    echo "Installed StackHawk skills to ${dest}/"
    echo "  hawkscan/ — DAST scanning skill"
    echo "  api/      — API reporting skill"
    ;;

  *)
    echo "ERROR: Unknown platform '${platform}'. Use 'cursor' or 'copilot'." >&2
    exit 1
    ;;
esac
