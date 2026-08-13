# GENERATED — do not edit

Produced by `scripts/generate-wingman-skills.sh`. Edit the source skills under
`plugins/*/skills/*/` and regenerate.

These are bundled copies of wingman's four dependency skills, present so GitHub
Copilot gets the full set from one `copilot plugin install wingman@stackhawk`.
Copilot has no plugin-dependency mechanism; Claude Code and Codex resolve
wingman's `dependencies` field and ignore this directory.

This directory is intentionally NOT named `skills/`: Claude Code always scans a
plugin's `skills/` directory, which would load every skill twice.
