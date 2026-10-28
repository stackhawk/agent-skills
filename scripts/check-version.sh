#!/usr/bin/env bash
set -euo pipefail

# ─── Version Consistency Check ───
# Every version-bearing file listed in .version-bump.json (and every generated wingman
# copy) must carry one version: the in-tree placeholder by default, or the version
# the release job just stamped. Files under "unversioned" must carry none, so Claude
# Code keeps tracking the commit instead of a number that never changes.
# Usage: ./scripts/check-version.sh [<expected-version>]

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 - "${1:-}" <<'PYEOF'
import glob
import json
import re
import sys

manifest = json.load(open(".version-bump.json"))
expected = sys.argv[1] or manifest["placeholder"]
errors = 0


def frontmatter_version(path):
    with open(path) as f:
        head = f.read().split("\n")[:20]
    for line in head:
        if line.startswith("version:"):
            return line[len("version:"):].strip()
    return None


def check(path, actual):
    global errors
    if actual != expected:
        print(f"ERROR: {path} has version {actual!r}, expected {expected!r}")
        errors += 1
    else:
        print(f"OK: {path} ({actual})")


for entry in manifest["files"]:
    path = entry["path"]
    if entry["type"] == "yaml-frontmatter":
        check(path, frontmatter_version(path))
    else:
        check(path, json.load(open(path)).get(entry["field"]))

# Skills and generated copies that bump-version.sh does not list.
listed = {e["path"] for e in manifest["files"]}
for path in sorted(glob.glob("plugins/*/skills/*/SKILL.md") + glob.glob("plugins/wingman/copilot-skills/*/SKILL.md")):
    if path not in listed:
        check(path, frontmatter_version(path))

for path in manifest["unversioned"]:
    data = json.load(open(path))
    versions = [data.get("version")] if "plugins" not in data else [p.get("version") for p in data["plugins"]]
    if any(v is not None for v in versions):
        print(f"ERROR: {path} must not carry a version (the release stamps it); remove the field")
        errors += 1
    else:
        print(f"OK: {path} (unversioned)")

if not re.fullmatch(r"\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?", expected):
    print(f"ERROR: expected version {expected!r} is not X.Y.Z")
    errors += 1
sys.exit(1 if errors else 0)
PYEOF
