# GENERATED - do not edit

The Cursor-only `wingman` plugin. Only the Cursor catalog (`.cursor-plugin/marketplace.json`)
lists this folder. The Claude and Codex catalogs list `plugins/wingman`, which carries no Cursor file.

The Cursor app and the Cursor CLI import Claude Code plugins. So the router rule and the stop
hook live only in folders that no Claude or Codex catalog lists, and the Claude hooks of
`plugins/hawkscan` do nothing when Cursor runs them. A Claude Code install then adds no second
router rule and no second stop hook to the native Cursor install of `wingman`. Cursor installs
this folder alone, so it carries its own copies of the bundled skills, the router rule, the
`stackhawk.yml` rule and the stop hook.

- `skills/`: from `scripts/generate-wingman-skills.sh`, identical to `plugins/wingman/copilot-skills/`.
- Everything else: from `scripts/generate-cursor-adapter.py`, which copies the rules and the
  Cursor hooks of `cursor-src/`.

Edit the sources and run both scripts. Never list this folder in a Claude or Codex catalog.
Released builds come from `stackhawk/agent-skills-marketplace`: its `bundles/wingman/` holds
the Cursor files of this plugin next to the Copilot and Codex ones.
