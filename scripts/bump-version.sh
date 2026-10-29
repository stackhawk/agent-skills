#!/usr/bin/env bash
set -euo pipefail

# ─── Version Stamp Script ───
# Releases are numbered by tags (biodome-rs ci version), not by a number committed in
# the tree. The tree carries a placeholder; the release job stamps the resolved
# version into every file listed in .version-bump.json to validate the tagged tree,
# and the marketplace sync stamps it into the snapshot it publishes.
# Handles two file types: json, yaml-frontmatter. A "stamp_only" json file carries no
# version in the tree: a release stamp adds the field and --placeholder removes it.
# Usage: ./scripts/bump-version.sh <X.Y.Z>|--placeholder
# Examples:
#   ./scripts/bump-version.sh 2.7.2          # stamp a release version
#   ./scripts/bump-version.sh --placeholder  # put the in-tree placeholder back

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${REPO_ROOT}/.version-bump.json"

if [ $# -ne 1 ]; then
  echo "Usage: $0 <X.Y.Z>|--placeholder" >&2
  exit 1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: .version-bump.json not found at ${MANIFEST}" >&2
  exit 1
fi

placeholder=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['placeholder'])" "$MANIFEST")

case "$1" in
  --placeholder) new_version="$placeholder" ;;
  *)             new_version="$1" ;;
esac

if ! printf '%s' "$new_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "ERROR: Version must be in X.Y.Z or X.Y.Z-prerelease format" >&2
  exit 1
fi

echo "Stamping version: ${new_version}"
echo ""

python3 - "$REPO_ROOT" "$MANIFEST" "$new_version" "$placeholder" <<'PYEOF'
import json
import re
import sys
import os

repo_root, manifest_path, new_ver, placeholder = sys.argv[1:5]

with open(manifest_path) as f:
    manifest = json.load(f)

updated = 0

def update_json_file(path, field, new_ver, stamp_only):
    with open(path) as f:
        data = json.load(f)
    if stamp_only:
        data.pop(field, None)
        if new_ver != placeholder:
            items = list(data.items())
            data = dict(items[:1] + [(field, new_ver)] + items[1:])
    elif field in data:
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
    if file_type == "json":
        update_json_file(abs_path, field, new_ver, entry.get("stamp_only", False))
    elif file_type == "yaml-frontmatter":
        update_yaml_frontmatter(abs_path, field, new_ver)
    print(f"  Updated: {entry['path']}")
    updated += 1

print(f"\nDone. Stamped {updated} file(s) with {new_ver}")
print("Run the generators next (generate-wingman-skills.sh): their copies carry the version.")
PYEOF
