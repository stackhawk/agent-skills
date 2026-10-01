# GENERATED — do not edit

Produced by `scripts/generate-wingman-skills.sh`. Edit the source skills under
`plugins/*/skills/*/` and regenerate.

These are bundled copies of wingman's four dependency skills, present so GitHub
Copilot and Codex get the full set from one wingman install. Neither installs
plugin dependencies, so both manifests point their `skills` field here. Claude
Code resolves wingman's `dependencies` field and ignores this directory.

This directory is intentionally NOT named `skills/`: Claude Code always scans a
plugin's `skills/` directory, which would load every skill twice.
