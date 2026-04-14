#!/usr/bin/env bash
set -euo pipefail

# ─── Version Bump Script ───
# Updates VERSION file and all platform manifests in one pass.
# Usage: ./scripts/bump-version.sh <new-version>
# Example: ./scripts/bump-version.sh 1.1.0

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -ne 1 ]; then
  echo "Usage: $0 <new-version>" >&2
  echo "Example: $0 1.1.0" >&2
  exit 1
fi

new_version="$1"

# Validate version format (semver-ish: X.Y.Z)
if ! printf '%s' "$new_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "ERROR: Version must be in X.Y.Z format (e.g., 1.2.3)" >&2
  exit 1
fi

old_version=$(cat "${REPO_ROOT}/VERSION")

if [ "$old_version" = "$new_version" ]; then
  echo "Version is already ${new_version}. Nothing to do."
  exit 0
fi

echo "Bumping version: ${old_version} → ${new_version}"
echo ""

# Update VERSION file
printf '%s' "$new_version" > "${REPO_ROOT}/VERSION"
echo "  Updated: VERSION"

# Find and update all JSON manifests containing a "version" field
manifests=(
  "${REPO_ROOT}/plugins/hawkscan/.claude-plugin/plugin.json"
  "${REPO_ROOT}/plugins/hawkscan/.codex-plugin/plugin.json"
  "${REPO_ROOT}/plugins/api/.claude-plugin/plugin.json"
  "${REPO_ROOT}/plugins/api/.codex-plugin/plugin.json"
  "${REPO_ROOT}/.codex-plugin/plugin.json"
  "${REPO_ROOT}/gemini-extension.json"
)

# Marketplace manifests have version inside plugin entries
marketplace_manifests=(
  "${REPO_ROOT}/.claude-plugin/marketplace.json"
)

updated=0

for manifest in "${manifests[@]}"; do
  if [ -f "$manifest" ]; then
    python3 -c "
import json, sys
with open('$manifest', 'r') as f:
    data = json.load(f)
if 'version' in data:
    data['version'] = '$new_version'
with open('$manifest', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"
    relative="${manifest#"${REPO_ROOT}/"}"
    echo "  Updated: ${relative}"
    updated=$((updated + 1))
  fi
done

for manifest in "${marketplace_manifests[@]}"; do
  if [ -f "$manifest" ]; then
    python3 -c "
import json, sys
with open('$manifest', 'r') as f:
    data = json.load(f)
if 'plugins' in data:
    for plugin in data['plugins']:
        if 'version' in plugin:
            plugin['version'] = '$new_version'
with open('$manifest', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"
    relative="${manifest#"${REPO_ROOT}/"}"
    echo "  Updated: ${relative} (plugin entries)"
    updated=$((updated + 1))
  fi
done

echo ""
echo "Done. Updated VERSION + ${updated} manifest(s) from ${old_version} → ${new_version}."
echo "Run 'git diff' to review changes before committing."
