#!/usr/bin/env bash
# Verifies generate-wingman-skills.sh output is complete and idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DEST="plugins/wingman/copilot-skills"
EXPECTED=(hawkscan stackhawk-api stackhawk-data-seed stackhawk-optimize)
errors=0

# 1. No skills/ directory may exist in wingman — Claude Code always scans it.
if [ -e "plugins/wingman/skills" ]; then
  echo "ERROR: plugins/wingman/skills exists — Claude Code would load duplicate skills"
  errors=$((errors + 1))
fi

# 2. Every expected skill directory exists with a SKILL.md.
for name in "${EXPECTED[@]}"; do
  if [ ! -f "${DEST}/${name}/SKILL.md" ]; then
    echo "ERROR: missing ${DEST}/${name}/SKILL.md"
    errors=$((errors + 1))
  else
    echo "OK: ${DEST}/${name}/SKILL.md"
  fi
done

# 3. hawkscan-ci must NOT be bundled — it is not a wingman dependency.
if [ -e "${DEST}/hawkscan-ci" ]; then
  echo "ERROR: ${DEST}/hawkscan-ci must not exist (not a wingman dependency)"
  errors=$((errors + 1))
fi

# 4. No symlinks in the output — they dangle after marketplace subdir extraction.
if find "$DEST" -type l | grep -q .; then
  echo "ERROR: symlinks found in ${DEST} — output must be real files"
  find "$DEST" -type l
  errors=$((errors + 1))
fi

# 5. Copied versions match VERSION (proves generation ran after bump-version.sh).
expected_version="$(cat VERSION)"
for name in "${EXPECTED[@]}"; do
  f="${DEST}/${name}/SKILL.md"
  [ -f "$f" ] || continue
  actual="$(head -20 "$f" | grep '^version:' | sed 's/version: //')"
  if [ "$actual" != "$expected_version" ]; then
    echo "ERROR: $f has version '$actual', expected '$expected_version' (run bump-version.sh before generating)"
    errors=$((errors + 1))
  fi
done

# 6. Copilot manifest exists, is valid JSON, and points at copilot-skills/.
MANIFEST="plugins/wingman/.github/plugin/plugin.json"
if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: missing $MANIFEST"
  errors=$((errors + 1))
else
  python3 -m json.tool "$MANIFEST" > /dev/null || {
    echo "ERROR: $MANIFEST is not valid JSON"
    errors=$((errors + 1))
  }
  skills_field="$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('skills',''))")"
  if [ "$skills_field" != "./copilot-skills/" ]; then
    echo "ERROR: $MANIFEST skills field is '$skills_field', expected './copilot-skills/'"
    errors=$((errors + 1))
  fi
  # Must NOT carry dependencies — Copilot ignores it and it misleads readers.
  if python3 -c "import json,sys; sys.exit(0 if 'dependencies' in json.load(open('$MANIFEST')) else 1)"; then
    echo "ERROR: $MANIFEST must not declare 'dependencies' (Copilot has no such mechanism)"
    errors=$((errors + 1))
  fi
  mver="$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('version','MISSING'))")"
  if [ "$mver" != "$expected_version" ]; then
    echo "ERROR: $MANIFEST has version '$mver', expected '$expected_version'"
    errors=$((errors + 1))
  fi
fi

if [ $errors -gt 0 ]; then
  echo "FAILED: $errors error(s)"
  exit 1
fi
echo "PASS: wingman copilot-skills valid"
