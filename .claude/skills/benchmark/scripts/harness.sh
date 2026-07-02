#!/usr/bin/env bash
# Sourced by run.sh. Requires: AGENT_SKILLS_REPO, SKILL_SUBPATH, SCRIPTS_DIR.
set -euo pipefail

materialize_skill() {  # <ref> <dest_dir>
  local ref="$1" dest="$2" name; name="$(basename "$SKILL_SUBPATH")"
  local depth; depth="$(awk -F/ '{print NF}' <<<"$SKILL_SUBPATH")"
  local tarball; tarball="$(mktemp)"
  if ! git -C "$AGENT_SKILLS_REPO" archive "$ref" "$SKILL_SUBPATH" > "$tarball"; then
    rm -f "$tarball"; echo "materialize_skill: git archive failed for $ref $SKILL_SUBPATH" >&2; return 1
  fi
  rm -rf "$dest"; mkdir -p "$dest/$name"
  tar -x -C "$dest/$name" --strip-components="$depth" -f "$tarball"; rm -f "$tarball"
  test -f "$dest/$name/SKILL.md" || { echo "materialize_skill: no SKILL.md for $ref" >&2; return 1; }
}

build_config_dir() {  # <skill_src> <model> <cell_config> <profile> <workdir>
  local src="$1" model="$2" cfg="$3" profile="$4" workdir="$5"
  rm -rf "$cfg"; mkdir -p "$cfg/skills" "$cfg/hooks"
  cp -R "$src"/* "$cfg/skills/"
  cp "$SCRIPTS_DIR/guard.py" "$cfg/hooks/guard.py"
  python3 - "$model" "$cfg" "$profile" "$workdir" > "$cfg/settings.json" <<'PY'
import json, sys
model, cfg, profile, workdir = sys.argv[1:5]
cmd = f"python3 {cfg}/hooks/guard.py --profile {profile} --workdir {workdir}"
json.dump({
    "model": model,
    "enableAllProjectMcpServers": False,
    "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]},
}, sys.stdout, indent=2)
PY
}
