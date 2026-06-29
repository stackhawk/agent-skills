# Move skill-authoring to .claude/skills/ Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the `skill-authoring` skill from `plugins/skill-authoring/` (public marketplace plugin structure) into `.claude/skills/skill-authoring/` (maintainer-local Claude Code skill). Remove it from all public release paths (`skills/`, `.opencode/skills/`, `.cursor/skills/`, and Cursor rule generation). Add changelog-update guidance to the skill content.

**Architecture:** `.claude/skills/` is the Claude Code convention for project-scoped skills available to repo contributors. The current `.gitignore` blocks all of `.claude/`, so we add a negation rule to track `.claude/skills/` while leaving settings files ignored. The `skills/`, `.opencode/skills/`, and `.cursor/skills/` symlinks are the public distribution paths — skill-authoring is removed from all three. Plugin manifests are deleted. The Cursor rule generator entry is removed.

**Tech Stack:** Bash, symlinks, JSON, YAML frontmatter, Markdown, `.gitignore`

---

### Task 1: Update `.gitignore` to track `.claude/skills/`

**Files:**
- Modify: `.gitignore`

Git's blanket `.claude/` rule prevents tracking anything under `.claude/`. Carve out `.claude/skills/` so maintainer skills are version-controlled. The negation lines must come AFTER the `.claude/` line (git processes `.gitignore` top to bottom).

**Step 1: Edit `.gitignore`**

Replace:
```
.claude/
```
With:
```
.claude/
!.claude/skills/
!.claude/skills/**
```

**Step 2: Verify the negation works**

```bash
git check-ignore -v .claude/skills/
# → no output (not ignored)

git check-ignore -v .claude/settings.local.json
# → .gitignore:1:.claude/ (still ignored)
```

---

### Task 2: Create `.claude/skills/skill-authoring/` and move SKILL.md

**Files:**
- Create: `.claude/skills/skill-authoring/SKILL.md`

**Step 3: Create the target directory**

```bash
mkdir -p .claude/skills/skill-authoring
```

**Step 4: Copy SKILL.md to new location**

```bash
cp plugins/skill-authoring/skills/skill-authoring/SKILL.md .claude/skills/skill-authoring/SKILL.md
```

**Step 5: Verify copy is identical**

```bash
diff plugins/skill-authoring/skills/skill-authoring/SKILL.md .claude/skills/skill-authoring/SKILL.md
# → no output
```

---

### Task 3: Add changelog guidance to SKILL.md

**Files:**
- Modify: `.claude/skills/skill-authoring/SKILL.md`

Append a new `## Updating the Changelog` section at the end of the file body. The content to add:

```markdown
---

## Updating the Changelog

`CHANGELOG.md` at the repo root follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format and must be updated in the **same commit** as any substantive change.

### When to update

| Change | Required? |
|--------|-----------|
| New skill or plugin | Yes — `### Added` entry |
| New reference file added to a skill | Yes — `### Added` entry |
| Content update to existing skill | Yes — `### Changed` entry |
| Bug fix / correction in skill content | Yes — `### Fixed` entry |
| Structural repo change (new dir, script change) | Yes — `### Changed` entry |
| Version bump only (no content change) | No |
| Typo fix | No |

### Format

Add the entry under `## [Unreleased]` at the top of the changelog (create the section if it doesn't exist):

```markdown
## [Unreleased]

### Added
- `hawkscan` skill: added OAuth 2.0 authentication support

### Changed
- `skill-authoring` moved from `plugins/` to `.claude/skills/` (maintainer skill, not marketplace)
```

`release.sh` converts `[Unreleased]` to the version + date when cutting a release. Never add a version header manually for in-progress work.

### Rule

Every PR that adds or modifies skill content must include a CHANGELOG entry. PRs without entries should be rejected in review.
```

**Step 6: Verify SKILL.md body ≤ 500 lines**

```bash
wc -l .claude/skills/skill-authoring/SKILL.md
# body = total - ~10 (frontmatter); must be ≤ ~510 total
```

If body exceeds 500 lines, move the new changelog section to `references/changelog-guidance.md` and replace with a progressive-disclosure link (per the existing patterns described in the skill itself).

---

### Task 4: Remove `plugins/skill-authoring/` entirely

**Files:**
- Delete: `plugins/skill-authoring/` (all contents: manifests + nested SKILL.md)

**Step 7: Delete the plugin directory**

```bash
rm -rf plugins/skill-authoring/
```

**Step 8: Verify**

```bash
ls plugins/
# → api  hawkscan  hawkscan-ci  stackhawk-data-seed
# skill-authoring must NOT appear
```

---

### Task 5: Remove skill-authoring from all public release symlink directories

`skills/`, `.opencode/skills/`, and `.cursor/skills/` are the public distribution paths used by Gemini, Copilot, OpenCode, and Cursor. A maintainer-only skill must not live here.

**Step 9: Remove from `skills/`**

```bash
rm skills/skill-authoring
```

**Step 10: Verify**

```bash
ls skills/
# → skill-authoring must NOT appear
```

**Step 11: Remove from `.opencode/skills/`**

```bash
rm .opencode/skills/skill-authoring
```

**Step 12: Verify**

```bash
ls .opencode/skills/
# → skill-authoring must NOT appear
```

**Step 13: Remove from `.cursor/skills/`**

```bash
rm .cursor/skills/skill-authoring
```

**Step 14: Verify**

```bash
ls .cursor/skills/
# → skill-authoring must NOT appear
```

---

### Task 6: Remove skill-authoring from `scripts/generate-cursor-rules.sh`

**Files:**
- Modify: `scripts/generate-cursor-rules.sh`

The MAPPINGS array has an entry for `skill-authoring`. Since it's now internal, remove it. The Cursor rule it produced (`cursor/.cursor/rules/stackhawk-skill-authoring.mdc`) will also be deleted when the script regenerates.

**Step 15: Delete the skill-authoring line from MAPPINGS**

Find and remove this entry (line ~38):
```
"skill-authoring/skills/skill-authoring/SKILL.md|stackhawk-skill-authoring|Guides authoring...|**/SKILL.md,**/.claude-plugin/plugin.json,**/.codex-plugin/plugin.json|false"
```

**Step 16: Verify script runs cleanly**

```bash
bash scripts/generate-cursor-rules.sh
# → no errors
```

**Step 17: Verify the skill-authoring Cursor rule is gone**

```bash
ls cursor/.cursor/rules/stackhawk-skill-authoring.mdc 2>/dev/null && echo "ERROR: still exists" || echo "correctly removed"
# → correctly removed
```

**Step 18: Verify remaining rules are intact**

```bash
ls cursor/.cursor/rules/*.mdc | wc -l
# → should be one fewer than before (the removed skill-authoring rule)
```

---

### Task 7: Update `.version-bump.json`

**Files:**
- Modify: `.version-bump.json`

Remove the three `skill-authoring` entries (two plugin manifests + old SKILL.md path). Add a new entry for the SKILL.md at its new location so `bump-version.sh` keeps the frontmatter version in sync.

**Step 19: Edit `.version-bump.json`**

Remove:
```json
{ "path": "plugins/skill-authoring/.claude-plugin/plugin.json", "field": "version", "type": "json" },
{ "path": "plugins/skill-authoring/.codex-plugin/plugin.json", "field": "version", "type": "json" },
{ "path": "plugins/skill-authoring/skills/skill-authoring/SKILL.md", "field": "version", "type": "yaml-frontmatter" }
```

Add (alongside other SKILL.md frontmatter entries):
```json
{ "path": ".claude/skills/skill-authoring/SKILL.md", "field": "version", "type": "yaml-frontmatter" }
```

**Step 20: Validate JSON**

```bash
python3 -m json.tool .version-bump.json > /dev/null && echo "valid JSON"
# → valid JSON
```

---

### Task 8: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

**Step 21: Update the Structure section**

In the `## Structure` bullet list, change:
```
- `plugins/skill-authoring/` — Skill authoring rules and best practices guide (SKILL.md)
```
To:
```
- `.claude/skills/skill-authoring/` — Maintainer skill: authoring rules and best practices for contributors to this repo. Tracked in git via `.gitignore` negation; NOT distributed via marketplace.
```

**Step 22: Confirm no stale references remain**

```bash
grep -rn "plugins/skill-authoring" CLAUDE.md scripts/generate-cursor-rules.sh .version-bump.json
# → no output
```

---

### Task 9: Update `CHANGELOG.md`

**Files:**
- Modify: `CHANGELOG.md`

**Step 23: Add `[Unreleased]` section at the top**

Insert after the `# Changelog` header and Keep a Changelog / Semantic Versioning lines, before the first `## [x.y.z]` entry:

```markdown
## [Unreleased]

### Added
- `skill-authoring` skill: changelog update guidance — documents when and how to add CHANGELOG entries for every substantive skill change

### Changed
- `skill-authoring` moved from `plugins/skill-authoring/` to `.claude/skills/skill-authoring/` (maintainer skill, not a marketplace plugin)
- `.gitignore` updated: `.claude/skills/` is now tracked so contributor skills are version-controlled
- Removed `skill-authoring` from public release paths (`skills/`, `.opencode/skills/`, `.cursor/skills/`) and Cursor rule generation
```

---

### Task 10: Bump version and regenerate Cursor rules

**Step 24: Bump version**

This is a `--minor` change (structural move + new changelog capability in the skill):

```bash
bash scripts/bump-version.sh --minor
```

Expected: VERSION minor increments; `.claude/skills/skill-authoring/SKILL.md` frontmatter `version:` updates; all plugin manifests update.

**Step 25: Regenerate Cursor rules**

```bash
bash scripts/generate-cursor-rules.sh
```

**Step 26: Verify idempotency**

```bash
bash scripts/generate-cursor-rules.sh && git diff cursor/
# → no diff
```

---

### Task 11: Commit

**Step 27: Stage all changes**

```bash
git add .gitignore .claude/skills/ plugins/ skills/ .opencode/ .cursor/ \
        scripts/generate-cursor-rules.sh .version-bump.json CLAUDE.md \
        CHANGELOG.md cursor/ VERSION
git status
# Review staged list — confirm:
#   skill-authoring removed from skills/, .opencode/skills/, .cursor/skills/
#   plugins/skill-authoring/ deleted
#   .claude/skills/skill-authoring/ added
#   no stale plugins/skill-authoring paths anywhere
```

**Step 28: Commit**

```bash
git commit -m "feat: move skill-authoring to .claude/skills/, add changelog guidance

skill-authoring is a maintainer tool, not a marketplace plugin.
- Moves skill to .claude/skills/skill-authoring/ (tracked via .gitignore negation)
- Removes plugin manifests (.claude-plugin, .codex-plugin)
- Removes from public release paths (skills/, .opencode/skills/, .cursor/skills/)
- Removes Cursor rule generation entry for skill-authoring
- Updates .version-bump.json: new SKILL.md path, no manifest entries
- Adds changelog update guidance to the skill content"
```

**Step 29: Final smoke test**

```bash
# New location resolves
ls .claude/skills/skill-authoring/SKILL.md

# Old plugin is gone
ls plugins/ | grep skill-authoring && echo "ERROR" || echo "correctly removed"

# Not in public release paths
ls skills/ .opencode/skills/ .cursor/skills/ | grep skill-authoring && echo "ERROR" || echo "correctly removed"

# Cursor rule is gone
ls cursor/.cursor/rules/stackhawk-skill-authoring.mdc 2>/dev/null && echo "ERROR: still exists" || echo "correctly removed"

# JSON valid
python3 -m json.tool .version-bump.json > /dev/null && echo "version-bump.json valid"

# No stale references
grep -rn "plugins/skill-authoring" . --include="*.json" --include="*.md" --include="*.sh" 2>/dev/null
# → no output
```

---

## Risk Notes

- **`.gitignore` negation order** — `!.claude/skills/` must come after `.claude/` in the file or git ignores the negation.
- **`generate-cursor-rules.sh` MAPPINGS count** — count entries before and after to confirm exactly one was removed (not more).
- **`.version-bump.json` trailing comma** — removing entries can leave a trailing comma before `]`. Validate with `python3 -m json.tool` after editing.
- **CI `generate-and-validate.yml`** — validates version consistency and Cursor rule sync. The bump + regenerate in Task 10 ensures both pass.
