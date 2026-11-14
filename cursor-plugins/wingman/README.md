# GENERATED - do not edit

The Cursor-only `wingman` plugin. Only the Cursor catalog (`.cursor-plugin/marketplace.json`)
lists this folder. The Claude and Codex catalogs list `plugins/wingman`.

Claude Code installs the dependencies of `wingman`, and the `hawkscan` dependency carries the
router rule and the stop hook. The Cursor app imports Claude Code plugins, so `plugins/wingman` must
carry no Cursor file: Cursor would load the router rule and the stop hook a second time.
Cursor has no plugin dependencies, so this folder carries its own copies of the bundled
skills, the router rule, the `stackhawk.yml` rule and the stop hook.

- `skills/`: from `scripts/generate-wingman-skills.sh`, identical to `plugins/wingman/copilot-skills/`.
- Everything else: from `scripts/generate-cursor-adapter.py`, which copies the rules and the
  Cursor hooks of `plugins/hawkscan/`.

Edit the sources and run both scripts. Never list this folder in a Claude or Codex catalog.
Released builds come from `stackhawk/agent-skills-marketplace`: its `bundles/wingman/` holds
the Cursor files of this plugin next to the Copilot and Codex ones.
