#!/usr/bin/env bash
# Stages the marketplace sync outputs in a marketplace checkout, and fails when the sync did
# not write one of them or changed anything else. The release runs it in validate, on a scratch
# clone after a dry-run sync where nothing is committed, and in update-marketplace before the
# commit. So such a sync fails before a release number is claimed.
#
# Keep PUBLISHED in sync with install() in the marketplace's scripts/sync-agent-skills.py.
# Usage: stage-marketplace-sync.sh <marketplace checkout>
set -euo pipefail

repo="${1:?usage: stage-marketplace-sync.sh <marketplace checkout>}"
PUBLISHED=(
  plugins bundles cursor-plugins skills install sources.json
  .claude-plugin/marketplace.json .github/plugin/marketplace.json
  .agents/plugins/marketplace.json .codex-plugin/marketplace.json
  .cursor-plugin/marketplace.json
)

for path in "${PUBLISHED[@]}"; do
  if [ ! -e "${repo}/${path}" ]; then
    echo "ERROR: the marketplace sync wrote no ${path}. Does the marketplace sync take --export?" >&2
    exit 1
  fi
done

git -C "$repo" add -A -- "${PUBLISHED[@]}"
if ! git -C "$repo" diff --quiet || [ -n "$(git -C "$repo" ls-files --others --exclude-standard)" ]; then
  echo "ERROR: the marketplace sync left changes outside the staged paths. Update PUBLISHED to match install()." >&2
  git -C "$repo" status --short >&2
  exit 1
fi
echo "Staged the marketplace sync outputs in ${repo}"
