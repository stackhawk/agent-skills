# Deprecated: generated Cursor rules

`cursor/.cursor/rules/` holds 28 rules that `scripts/generate-cursor-rules.sh` generates from the
skills. They are deprecated and will be removed in the next major release.

The installers no longer copy them, and they remove them from a project on upgrade. Each rule
body was a full copy of a skill file, and the always-applied `stackhawk-hawkscan.mdc` put about
30 KB into every Cursor chat. Cursor now reads the skills as Agent Skills, which load on demand,
and one small router rule (`cursor-src/rules/stackhawk.mdc`) names them.

Install for Cursor with `scripts/install.sh --platform cursor` (or `scripts/install.ps1`), or
load a plugin folder with `cursor-agent --plugin-dir cursor-plugins/hawkscan`. See the Cursor section of
the repository README.

Do not edit the `.mdc` files: they are generated, and CI checks them until `cursor/` is removed.
