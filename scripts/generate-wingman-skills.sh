#!/usr/bin/env bash
# Generates plugins/wingman/copilot-skills/ - bundled copies of wingman's four
# dependency skills, so GitHub Copilot and Codex (neither installs plugin
# dependencies) get the full skill set from one wingman install. It also points
# the Codex manifest's "skills" field at that directory.
#
# Claude Code resolves wingman's "dependencies" field instead and never reads
# this directory. It is deliberately NOT named skills/ - Claude Code always
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

# Validate all sources exist BEFORE destroying anything — a missing source
# must not leave the bundle half-deleted with no README.md.
for entry in "${MAPPINGS[@]}"; do
  src="${entry%%|*}"
  if [ ! -f "${src}/SKILL.md" ]; then
    echo "ERROR: source not found: ${src}/SKILL.md" >&2
    exit 1
  fi
done

# Full rebuild so files deleted from source do not linger.
rm -rf "$DEST"
mkdir -p "$DEST"

for entry in "${MAPPINGS[@]}"; do
  src="${entry%%|*}"
  name="${entry##*|}"
  # -L dereferences symlinks: this repo reaches skills through symlinks, and the
  # marketplace extracts only the plugins/wingman subdir, so links would dangle.
  cp -RL "$src" "${DEST}/${name}"

  # Namespace the skill name in the BUNDLED COPY ONLY, so Copilot users see
  # `stackhawk-api` / `stackhawk-optimize` instead of the generic `api` /
  # `optimize`. The source skills keep their current names, so Claude Code,
  # Codex, Cursor, Gemini, and OpenCode are untouched — renaming those is
  # breaking and ships separately.
  #
  # Note: a per-plugin Copilot install (`copilot plugin install
  # stackhawk-api@stackhawk`) reads the SOURCE skill, so it still shows the
  # generic name. Only the wingman bundle is namespaced here.
  src_name="$(grep -m1 '^name:' "${DEST}/${name}/SKILL.md" | sed 's/^name: *//')"
  if [ "$src_name" != "$name" ]; then
    # Rewrite only the first `name:` line (frontmatter); skill bodies contain
    # YAML examples with their own name: keys that must not be touched.
    perl -0pi -e "s/^name: .*$/name: ${name}/m" "${DEST}/${name}/SKILL.md"
    rewritten="$(grep -m1 '^name:' "${DEST}/${name}/SKILL.md" | sed 's/^name: *//')"
    if [ "$rewritten" != "$name" ]; then
      echo "ERROR: failed to rewrite name in ${DEST}/${name}/SKILL.md" >&2
      exit 1
    fi
    echo "Generated: ${DEST}/${name} (name: ${src_name} -> ${name})"
  else
    echo "Generated: ${DEST}/${name}"
  fi
done

cat > "${DEST}/README.md" << 'EOF'
# GENERATED — do not edit

Produced by `scripts/generate-wingman-skills.sh`. Edit the source skills under
`plugins/*/skills/*/` and regenerate.

These are bundled copies of wingman's four dependency skills, present so GitHub
Copilot and Codex get the full set from one wingman install. Neither installs
plugin dependencies, so both manifests point their `skills` field here. Claude
Code resolves wingman's `dependencies` field and ignores this directory.

This directory is intentionally NOT named `skills/`: Claude Code always scans a
plugin's `skills/` directory, which would load every skill twice.
EOF

# Codex ignores the "dependencies" field, so without this key wingman loads no
# skills in Codex. Write JSON the same way bump-version.sh does, so the two
# scripts never fight over formatting.
CODEX_MANIFEST="plugins/wingman/.codex-plugin/plugin.json"
python3 - "$CODEX_MANIFEST" << 'PY'
import json
import sys

path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
data["skills"] = "./copilot-skills/"
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
echo "Updated: ${CODEX_MANIFEST} (skills: ./copilot-skills/)"

echo "Done. Generated ${#MAPPINGS[@]} skill(s) into ${DEST}"
