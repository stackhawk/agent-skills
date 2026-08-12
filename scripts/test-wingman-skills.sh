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

if [ $errors -gt 0 ]; then
  echo "FAILED: $errors error(s)"
  exit 1
fi
echo "PASS: wingman copilot-skills valid"
