# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# StackHawk Agent Skills

Multi-platform agent skills repo serving Claude, Codex, Gemini, Copilot, Cursor, and OpenCode from one canonical source. Skills teach AI agents to run HawkScan DAST security scanning and query the StackHawk platform API.

## Structure

- `plugins/hawkscan/` — HawkScan DAST scanning skill (SKILL.md + references + hooks)
- `plugins/api/` — StackHawk API reporting skill (SKILL.md + references)
- `plugins/wingman/` — Umbrella plugin; `/plugin install wingman@stackhawk` installs hawkscan + api + data-seed + optimize
- `plugins/wingman/copilot-skills/` — Generated copies of wingman's four skills for GitHub Copilot and Codex, which ignore `dependencies` (do NOT edit)
- `.claude/skills/skill-authoring/` — Maintainer skill: authoring rules and best practices for contributors to this repo (NOT distributed via marketplace; tracked in git via `.gitignore` negation; NOT in `.version-bump.json` — it carries its own version, independent of the release version)
- `skills/` — Symlinks for Gemini/Copilot discovery (points into plugins/)
- `.opencode/skills/` — Symlinks for OpenCode discovery (points into plugins/)
- `.cursor/skills/` — Symlinks for Cursor native skills discovery (points into plugins/)
- `plugins/hawkscan/hooks/cursor/` — Cursor hook scripts and hooks.json
- `cursor/` — Generated Cursor .mdc rules (do NOT edit manually)
- `scripts/generate-cursor-rules.sh` — Transforms SKILL.md → Cursor .mdc format
- `scripts/bump-version.sh` — Stamps one version into every version-bearing file (reads `.version-bump.json`); the release job uses it, contributors never do
- `scripts/check-version.sh` — Checks every version-bearing file carries one version (the placeholder by default)
- `scripts/generate-marketplace-catalogs.py` and `scripts/generate-marketplace-skills.py`: Local install verification helpers; release publishing uses the marketplace repo's `scripts/sync-agent-skills.py`

## Commands

```bash
# Regenerate Cursor rules after editing any SKILL.md or references/*.md
bash scripts/generate-cursor-rules.sh

# Verify generation is idempotent (no diff = correct)
bash scripts/generate-cursor-rules.sh && git diff cursor/

# Releases are numbered by tags: do not bump anything in a PR. After a stamp, put the placeholder back:
bash scripts/bump-version.sh --placeholder && bash scripts/check-version.sh

# macOS/Linux install
bash scripts/install.sh --platform cursor  --target ~
bash scripts/install.sh --platform copilot --target ~

# Regenerate the wingman Copilot bundle after editing any bundled SKILL.md
bash scripts/generate-wingman-skills.sh

# Validate the bundle
bash scripts/test-wingman-skills.sh

# Preview the released marketplace layout in a disposable marketplace checkout:
# see the "Updating the pinned version" section of agent-skills-marketplace/README.md.
```

```powershell
# Windows install
.\scripts\install.ps1 -Platform cursor
.\scripts\install.ps1 -Platform copilot
```

## PR Workflow

Do not bump versions in a PR. Every merge to `main` is a release: `release.yml` takes the next number from the latest release tag (`Release: minor` or `Release: major` on a line of the PR description raises it further), checks the tree stamped with it, claims it, tags the merged commit and publishes. `generate-and-validate.yml` checks the tree still carries the placeholder.

See `RELEASING.md` for the release flow, recovery and the marketplace sync.

## Manifests and Versioning

Release tags (`vX.Y.Z`) are the source of truth; there is no `VERSION` file. The tree carries the placeholder `0.0.0-dev` (set in `.version-bump.json`) in every version-bearing file, and the manifests whose format allows it (Claude, Codex and Copilot manifests) carry no `version` at all so git-sourced installs track the commit; `gemini-extension.json` requires one and keeps the placeholder. The release job stamps the resolved version into a scratch copy to validate it, and the marketplace sync stamps it into the snapshot it publishes.

Skills assume the combined `hawk` binary (`hawk op …`) is installed — no raw-REST fallback.

| Platform | Manifest |
|----------|----------|
| Claude | `.claude-plugin/marketplace.json` + `plugins/*/.claude-plugin/plugin.json` |
| Codex | `.codex-plugin/marketplace.json` + `plugins/*/.codex-plugin/plugin.json` |
| Gemini | `gemini-extension.json` |
| Copilot | `plugins/wingman/.github/plugin/plugin.json` (umbrella only). A per-plugin Copilot install fetches e.g. `plugins/hawkscan`, reads that plugin's own `plugins/hawkscan/.claude-plugin/plugin.json`, and defaults to that plugin's own `plugins/hawkscan/skills/` directory — the repo-root `skills/` symlinks are NOT involved in marketplace per-plugin installs; they serve Gemini and the whole-repo `plugin.json` install only |
| Cursor | Rules: generated into `cursor/.cursor/rules/`; Skills: symlinks in `.cursor/skills/`; Hooks: `plugins/hawkscan/hooks/cursor/` |
| Claude (umbrella) | `plugins/wingman/.claude-plugin/plugin.json` — `/plugin install wingman@stackhawk` installs hawkscan + api + data-seed + optimize |

`.version-bump.json` lists every version-bearing file (`files`; `stamp_only` ones carry no version in the tree and get one when stamped) and every manifest that must stay unversioned (`unversioned`). `bump-version.sh` reads it to stamp all files atomically, and `check-version.sh` to verify them. When adding a new plugin, add its manifests and SKILL.md to `.version-bump.json`.

CI (`generate-and-validate.yml`) validates version consistency on every PR. `release.yml` runs on every push to `main` and ends in the marketplace sync. A failed run that already claimed its number is re-run, or freed with `abandon-release.yml`.

## Adding a New Plugin

1. Create `plugins/<name>/skills/<name>/SKILL.md` with `name:`, `version:`, `description:` frontmatter
2. Create `plugins/<name>/.claude-plugin/plugin.json` (with `icon.svg`) and `.codex-plugin/plugin.json`, plus `plugins/<name>/README.md`; see README "Claude directory validation"
3. Add symlinks in `skills/`, `.opencode/skills/`, and `.cursor/skills/` (pointing into the new plugin)
4. Add entries to `scripts/generate-cursor-rules.sh` `MAPPINGS` array (controls Cursor .mdc generation)
5. Add all new manifests and SKILL.md to `.version-bump.json`
6. Run `bash scripts/bump-version.sh --placeholder` so the new files carry the placeholder, then `bash scripts/check-version.sh`

## Cursor Rule Generation

`scripts/generate-cursor-rules.sh` contains a `MAPPINGS` array. Each entry maps a source file to a Cursor `.mdc` rule:

```
source_path|output_name|description|globs (comma-separated or empty)|alwaysApply
```

`cursor/` is generated output — never edit `.mdc` files directly. Edit the source SKILL.md or references, then regenerate. CI blocks PRs where cursor rules are out of sync.

## Cursor Hooks

Cursor hooks live in `plugins/hawkscan/hooks/cursor/` and are copied to users' projects by `install.sh`. They are NOT generated — edit them directly.

- `hooks.json` — Cursor hooks config (version 1, `stop` hook only)
- `stop.sh` — Fires when the agent loop ends; outputs `followup_message` to auto-trigger a scan if code was modified without scanning

The `stop` hook's `followup_message` causes Cursor to automatically continue with that message, prompting the agent to run the hawkscan skill. This is more powerful than the Claude Code equivalent (`stopReason` is display-only).

## Gotchas

- `cursor/` is generated output — edit the source SKILL.md, then regenerate
- `skills/`, `.opencode/skills/`, and `.cursor/skills/` entries are symlinks, not copies — don't break the relative paths
- Cursor skills `name:` field matches the symlink folder name for `hawkscan`, `hawkscan-ci`, and `stackhawk-data-seed`. It does NOT for the other two: symlinks `stackhawk-api` and `stackhawk-optimize` point at skills named `api` and `optimize`. Those skills are what users see in skill lists. Renaming them is a breaking change tracked as a separate major release.
- Cursor hook `command` path (`.cursor/hooks/stop.sh`) is relative to the project root — correct for both user-level (`~`) and project-level installs
- `docs/superpowers/` is gitignored (design specs/plans kept locally)
- `.claude/` dir is gitignored (local settings only)
- SKILL.md frontmatter requires `name:`, `version:`, and `description:` — CI validates all three
- `plugins/wingman/copilot-skills/` is generated output — edit the source skills and run `bash scripts/generate-wingman-skills.sh`
- `plugins/wingman/` must NEVER contain a `skills/` directory. Claude Code always scans `skills/`, so one would load every skill twice (`wingman:hawkscan` and `hawkscan:hawkscan`). The Copilot bundle is deliberately named `copilot-skills/`.
- Generated copies carry the version frontmatter copied from source: regenerate after stamping (the release job does) and after `--placeholder`
- The separate `agent-skills-marketplace` repo owns its generated catalogs, plugin snapshots, and `skills/` copies. `release.yml` runs that repo's sync script on a new tag and pushes validated outputs to marketplace `main`; never hand-edit its generated outputs. The standalone `skills/` copies serve the `skills` CLI, which ignores marketplace catalogs.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
