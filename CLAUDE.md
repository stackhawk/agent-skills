# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# StackHawk Agent Skills

Multi-platform agent skills repo serving Claude, Codex, Gemini, Copilot, Cursor, and OpenCode from one canonical source. Skills teach AI agents to run HawkScan DAST security scanning and query the StackHawk platform API.

## Structure

- `plugins/hawkscan/` — HawkScan DAST scanning skill (SKILL.md + references + hooks)
- `plugins/api/` — StackHawk API reporting skill (SKILL.md + references)
- `plugins/wingman/` — Umbrella plugin; `/plugin install wingman@stackhawk` installs hawkscan + api + data-seed + optimize
- `.claude/skills/skill-authoring/` — Maintainer skill: authoring rules and best practices for contributors to this repo (NOT distributed via marketplace; tracked in git via `.gitignore` negation)
- `skills/` — Symlinks for Gemini/Copilot discovery (points into plugins/)
- `.opencode/skills/` — Symlinks for OpenCode discovery (points into plugins/)
- `.cursor/skills/` — Symlinks for Cursor native skills discovery (points into plugins/)
- `plugins/hawkscan/hooks/cursor/` — Cursor hook scripts and hooks.json
- `cursor/` — Generated Cursor .mdc rules (do NOT edit manually)
- `scripts/generate-cursor-rules.sh` — Transforms SKILL.md → Cursor .mdc format
- `scripts/bump-version.sh` — Updates all version-bearing files atomically (reads `.version-bump.json`)
- `scripts/release.sh` — Pre-release checks, creates tag, creates GH Release

## Commands

```bash
# Regenerate Cursor rules after editing any SKILL.md or references/*.md
bash scripts/generate-cursor-rules.sh

# Verify generation is idempotent (no diff = correct)
bash scripts/generate-cursor-rules.sh && git diff cursor/

# Bump version (updates VERSION + all manifests + SKILL.md frontmatter in one pass)
bash scripts/bump-version.sh --patch   # bug fixes
bash scripts/bump-version.sh --minor   # new skill or significant capability
bash scripts/bump-version.sh --major   # breaking changes

# Release (validates everything, creates annotated tag, creates GH Release)
bash scripts/release.sh --dry-run  # validate without creating anything
bash scripts/release.sh            # create tag + GH Release (must be on main, clean tree)

# macOS/Linux install
bash scripts/install.sh --platform cursor  --target ~
bash scripts/install.sh --platform copilot --target ~
```

```powershell
# Windows install
.\scripts\install.ps1 -Platform cursor
.\scripts\install.ps1 -Platform copilot
```

## PR Workflow

Before creating every PR, bump the patch version and include it in the commit:

```bash
bash scripts/bump-version.sh --patch
```

Use `--minor` for new skills or significant capability additions, `--major` for breaking changes.

See `RELEASING.md` for the full release process including how to update the marketplace catalog.

## Manifests and Versioning

`VERSION` is the single source of truth. All platform manifests must match it.

Skills assume the combined `hawk` binary (`hawk op …`) is installed — no raw-REST fallback.

| Platform | Manifest |
|----------|----------|
| Claude | `.claude-plugin/marketplace.json` + `plugins/*/.claude-plugin/plugin.json` |
| Codex | `.codex-plugin/marketplace.json` + `plugins/*/.codex-plugin/plugin.json` |
| Gemini | `gemini-extension.json` |
| Copilot | No manifest — discovers via `skills/` symlinks |
| Cursor | Rules: generated into `cursor/.cursor/rules/`; Skills: symlinks in `.cursor/skills/`; Hooks: `plugins/hawkscan/hooks/cursor/` |
| Claude (umbrella) | `plugins/wingman/.claude-plugin/plugin.json` — `/plugin install wingman@stackhawk` installs hawkscan + api + data-seed + optimize |

`.version-bump.json` lists every version-bearing file. `bump-version.sh` reads it to update all files atomically. When adding a new plugin, add its manifests and SKILL.md to `.version-bump.json`.

CI (`generate-and-validate.yml`) validates version consistency on every PR. The `release.yml` workflow fires on `v*.*.*` tag pushes and re-validates before creating the GH Release.

## Adding a New Plugin

1. Create `plugins/<name>/skills/<name>/SKILL.md` with `name:`, `version:`, `description:` frontmatter
2. Create `plugins/<name>/.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`
3. Add symlinks in `skills/`, `.opencode/skills/`, and `.cursor/skills/` (pointing into the new plugin)
4. Add entries to `scripts/generate-cursor-rules.sh` `MAPPINGS` array (controls Cursor .mdc generation)
5. Add all new manifests and SKILL.md to `.version-bump.json`
6. Run `bash scripts/bump-version.sh --minor` so version propagates

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
- Cursor skills `name:` field must match the symlink folder name (they all do: `hawkscan`, `api`, `hawkscan-ci`, `stackhawk-data-seed`)
- Cursor hook `command` path (`.cursor/hooks/stop.sh`) is relative to the project root — correct for both user-level (`~`) and project-level installs
- `docs/superpowers/` is gitignored (design specs/plans kept locally)
- `.claude/` dir is gitignored (local settings only)
- SKILL.md frontmatter requires `name:`, `version:`, and `description:` — CI validates all three
- `scripts/release.sh` must be run from `main` with a clean working tree
