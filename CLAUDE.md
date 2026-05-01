# StackHawk Agent Skills

Multi-platform agent skills repo serving Claude, Codex, Gemini, Copilot, and Cursor from one canonical source.

## Structure

- `plugins/hawkscan/` — HawkScan DAST scanning skill (SKILL.md + references)
- `plugins/api/` — StackHawk API reporting skill (SKILL.md + references)
- `skills/` — Symlinks for Gemini/Copilot discovery (points into plugins/)
- `.opencode/skills/` — Symlinks for OpenCode discovery (points into plugins/)
- `cursor/` — Generated Cursor .mdc rules (do NOT edit manually)
- `scripts/generate-cursor-rules.sh` — Transforms SKILL.md → Cursor .mdc format

## Commands

```bash
# Regenerate Cursor rules after editing any SKILL.md or references/*.md
bash scripts/generate-cursor-rules.sh

# Verify generation is idempotent (no diff = correct)
bash scripts/generate-cursor-rules.sh && git diff cursor/
```

## PR Workflow

Before creating every PR, bump the patch version and include it in the commit:

```bash
bash scripts/bump-version.sh --patch
```

Use `--minor` for new skills or significant capability additions, `--major` for breaking changes.
The script updates `VERSION` and all platform manifests in one pass.

## Manifests

All platform manifests share the version in `VERSION` (single source of truth).

| Platform | Manifest |
|----------|----------|
| Claude | `.claude-plugin/marketplace.json` + `plugins/*/.claude-plugin/plugin.json` |
| Codex | `.codex-plugin/marketplace.json` + `plugins/*/.codex-plugin/plugin.json` |
| Gemini | `gemini-extension.json` |
| Copilot | No manifest — discovers via `skills/` symlinks |
| Cursor | Generated into `cursor/.cursor/rules/` |

## Gotchas

- `cursor/` is generated output — edit the source SKILL.md, then regenerate
- `skills/` and `.opencode/skills/` entries are symlinks, not copies — don't break the relative paths
- `docs/superpowers/` is gitignored (design specs/plans kept locally)
- `.claude/` dir is gitignored (local settings only)
