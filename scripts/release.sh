#!/usr/bin/env bash
set -euo pipefail

# ─── Release Script ───
# Validates the repo state, creates a git tag, and creates a GitHub Release.
# Usage: ./scripts/release.sh [--dry-run]
# Reads version from VERSION file. Requires gh CLI for GitHub Release creation.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
  echo "=== DRY RUN MODE ==="
  echo ""
fi

version=$(cat "${REPO_ROOT}/VERSION")
tag="v${version}"

echo "Preparing release: ${tag}"
echo ""

# ─── Safety Checks ───

errors=0

# 1. Clean working tree
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Working tree is not clean. Commit or stash changes first." >&2
  errors=$((errors + 1))
fi

# 2. On main branch
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" != "main" ]; then
  echo "ERROR: Not on main branch (currently on '${current_branch}'). Switch to main first." >&2
  errors=$((errors + 1))
fi

# 3. Tag doesn't already exist
if git rev-parse "$tag" >/dev/null 2>&1; then
  echo "ERROR: Tag '${tag}' already exists. Bump VERSION first." >&2
  errors=$((errors + 1))
fi

# 4. Cursor rules are up to date
bash "${REPO_ROOT}/scripts/generate-cursor-rules.sh" > /dev/null
git add -N cursor/
if ! git diff --quiet cursor/; then
  echo "ERROR: Cursor rules are out of date. Run 'bash scripts/generate-cursor-rules.sh' and commit." >&2
  errors=$((errors + 1))
fi

# 5. Version consistency across manifests
expected="$version"
for manifest in plugins/*/.claude-plugin/plugin.json plugins/*/.codex-plugin/plugin.json plugins/*/.github/plugin/plugin.json gemini-extension.json .codex-plugin/plugin.json; do
  if [ -f "$manifest" ]; then
    actual=$(python3 -c "import json; print(json.load(open('$manifest')).get('version', 'MISSING'))")
    if [ "$actual" != "$expected" ]; then
      echo "ERROR: ${manifest} has version '${actual}', expected '${expected}'" >&2
      errors=$((errors + 1))
    fi
  fi
done

# 6. Wingman Copilot bundle is valid and up to date
bash "${REPO_ROOT}/scripts/test-wingman-skills.sh" || errors=$((errors + 1))
bash "${REPO_ROOT}/scripts/generate-wingman-skills.sh" > /dev/null
git add -N plugins/wingman/copilot-skills/
if ! git diff --quiet plugins/wingman/copilot-skills/; then
  echo "ERROR: wingman copilot-skills/ is out of date. Run 'bash scripts/generate-wingman-skills.sh' and commit." >&2
  errors=$((errors + 1))
fi

if [ $errors -gt 0 ]; then
  echo ""
  echo "FAILED: ${errors} pre-release check(s) failed. Fix the issues above and retry." >&2
  exit 1
fi

echo "All pre-release checks passed."
echo ""

if [ "$DRY_RUN" = true ]; then
  echo "DRY RUN: Would create tag '${tag}' and GitHub Release."
  echo "DRY RUN: Run without --dry-run to execute."
  exit 0
fi

# ─── Create Tag ───

echo "Creating annotated tag: ${tag}"
git tag -a "$tag" -m "${tag}: Release"

echo "Pushing tag to origin..."
git push origin "$tag"

# ─── Create GitHub Release ───

if ! command -v gh >/dev/null 2>&1; then
  echo ""
  echo "WARNING: gh CLI not found. Tag pushed but GitHub Release not created."
  echo "Create it manually: gh release create ${tag} --title '${tag}' --notes-file CHANGELOG.md"
  exit 0
fi

# Extract the current version's changelog section
changelog_body=""
if [ -f "${REPO_ROOT}/CHANGELOG.md" ]; then
  changelog_body=$(awk "/^## \\[${version}\\]/{found=1; next} /^## \\[/{found=0} found" "${REPO_ROOT}/CHANGELOG.md")
fi

if [ -z "$changelog_body" ]; then
  changelog_body="Release ${tag}"
fi

echo "Creating GitHub Release..."
gh release create "$tag" \
  --title "$tag" \
  --notes "$changelog_body"

echo ""
echo "Release ${tag} created successfully."
echo "  Tag: ${tag}"
echo "  GitHub Release: $(gh release view "$tag" --json url -q '.url' 2>/dev/null || echo 'check GitHub')"
