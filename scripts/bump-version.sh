#!/usr/bin/env bash
set -euo pipefail

# ─── Version Bump Script ───
# Reads .version-bump.json to find every file needing a version update.
# Handles three file types: raw (VERSION), json, yaml-frontmatter.
# Usage: ./scripts/bump-version.sh --patch|--minor|--major|<new-version>
# Examples:
#   ./scripts/bump-version.sh --patch   # 1.3.0 → 1.3.1
#   ./scripts/bump-version.sh --minor   # 1.3.0 → 1.4.0
#   ./scripts/bump-version.sh --major   # 1.3.0 → 2.0.0
#   ./scripts/bump-version.sh 1.5.0     # explicit version

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${REPO_ROOT}/.version-bump.json"

if [ $# -ne 1 ]; then
  echo "Usage: $0 --patch|--minor|--major|<new-version>" >&2
  exit 1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: .version-bump.json not found at ${MANIFEST}" >&2
  exit 1
fi

current_version=$(cat "${REPO_ROOT}/VERSION")
IFS='.' read -r major minor patch_ver <<< "${current_version%%-*}"

case "$1" in
  --patch) new_version="${major}.${minor}.$((patch_ver + 1))" ;;
  --minor) new_version="${major}.$((minor + 1)).0" ;;
  --major) new_version="$((major + 1)).0.0" ;;
  *)       new_version="$1" ;;
esac

if ! printf '%s' "$new_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "ERROR: Version must be in X.Y.Z or X.Y.Z-prerelease format" >&2
  exit 1
fi

old_version=$(cat "${REPO_ROOT}/VERSION")

if [ "$old_version" = "$new_version" ]; then
  echo "Version is already ${new_version}. Nothing to do."
  exit 0
fi

echo "Bumping version: ${old_version} → ${new_version}"
echo ""

python3 - "$REPO_ROOT" "$MANIFEST" "$old_version" "$new_version" <<'PYEOF'
import json
import re
import sys
import os

repo_root, manifest_path, old_ver, new_ver = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

with open(manifest_path) as f:
    manifest = json.load(f)

updated = 0

def update_json_file(path, field, new_ver):
    with open(path) as f:
        data = json.load(f)
    if field in data:
        data[field] = new_ver
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

def update_yaml_frontmatter(path, field, new_ver):
    with open(path) as f:
        content = f.read()
    pattern = rf'^{re.escape(field)}: [^\n]+'
    new_content = re.sub(pattern, f'{field}: {new_ver}', content, count=1, flags=re.MULTILINE)
    with open(path, 'w') as f:
        f.write(new_content)

for entry in manifest.get("files", []):
    abs_path = os.path.join(repo_root, entry["path"])
    if not os.path.exists(abs_path):
        print(f"  SKIP (not found): {entry['path']}")
        continue
    file_type = entry.get("type", "json")
    field = entry["field"]
    if file_type == "raw":
        with open(abs_path, 'w') as f:
            f.write(new_ver)
    elif file_type == "json":
        update_json_file(abs_path, field, new_ver)
    elif file_type == "yaml-frontmatter":
        update_yaml_frontmatter(abs_path, field, new_ver)
    print(f"  Updated: {entry['path']}")
    updated += 1

for entry in manifest.get("marketplace_manifests", []):
    abs_path = os.path.join(repo_root, entry["path"])
    if not os.path.exists(abs_path):
        print(f"  SKIP (not found): {entry['path']}")
        continue
    with open(abs_path) as f:
        data = json.load(f)
    if "plugins" in data:
        for plugin in data["plugins"]:
            if entry["field"] in plugin:
                plugin[entry["field"]] = new_ver
    with open(abs_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print(f"  Updated: {entry['path']} (plugin entries)")
    updated += 1

print(f"\nDone. Updated {updated} file(s): {old_ver} → {new_ver}")
print("Run 'git diff' to review changes before committing.")
PYEOF
