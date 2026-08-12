#!/usr/bin/env bash
# Generates plugins/wingman/copilot-skills/ — bundled copies of wingman's four
# dependency skills, so GitHub Copilot (which has no plugin dependency mechanism)
# gets the full skill set from a single `copilot plugin install wingman@stackhawk`.
#
# Claude Code and Codex resolve wingman's "dependencies" field instead and never
# read this directory. It is deliberately NOT named skills/ — Claude Code always
# scans skills/, which would load every skill twice.
#
# Run AFTER scripts/bump-version.sh so copied frontmatter carries the new version.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DEST="plugins/wingman/copilot-skills"

# source_path|generated_dir_name  (generated name = marketplace plugin name)
MAPPINGS=(
  "plugins/hawkscan/skills/hawkscan|hawkscan"
  "plugins/api/skills/api|stackhawk-api"
  "plugins/stackhawk-data-seed/skills/stackhawk-data-seed|stackhawk-data-seed"
  "plugins/optimize/skills/optimize|stackhawk-optimize"
)

# Full rebuild so files deleted from source do not linger.
rm -rf "$DEST"
mkdir -p "$DEST"

for entry in "${MAPPINGS[@]}"; do
  src="${entry%%|*}"
  name="${entry##*|}"
  if [ ! -f "${src}/SKILL.md" ]; then
    echo "ERROR: source not found: ${src}/SKILL.md" >&2
    exit 1
  fi
  # -L dereferences symlinks: this repo reaches skills through symlinks, and the
  # marketplace extracts only the plugins/wingman subdir, so links would dangle.
  cp -RL "$src" "${DEST}/${name}"
  echo "Generated: ${DEST}/${name}"
done

cat > "${DEST}/README.md" << 'EOF'
# GENERATED — do not edit

Produced by `scripts/generate-wingman-skills.sh`. Edit the source skills under
`plugins/*/skills/*/` and regenerate.

These are bundled copies of wingman's four dependency skills, present so GitHub
Copilot gets the full set from one `copilot plugin install wingman@stackhawk`.
Copilot has no plugin-dependency mechanism; Claude Code and Codex resolve
wingman's `dependencies` field and ignore this directory.

This directory is intentionally NOT named `skills/`: Claude Code always scans a
plugin's `skills/` directory, which would load every skill twice.
EOF

echo "Done. Generated ${#MAPPINGS[@]} skill(s) into ${DEST}"
