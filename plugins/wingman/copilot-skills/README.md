# GENERATED — do not edit

Produced by `scripts/generate-wingman-skills.sh`. Edit the source skills under
`plugins/*/skills/*/` and regenerate.

These are bundled copies of wingman's four dependency skills, present so GitHub
Copilot, Codex and Cursor get the full set from one wingman install. None of
them installs plugin dependencies, so their manifests point their `skills` field
here. Claude Code resolves wingman's `dependencies` field and ignores this
directory.

This directory is intentionally NOT named `skills/`: Claude Code always scans a
plugin's `skills/` directory, which would load every skill twice.
