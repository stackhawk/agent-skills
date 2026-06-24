---
name: skill-authoring
version: 1.14.3
description: >
  Guides authoring and maintaining agent skills in this repository — enforcing
  Anthropic best practices, bumping versions, regenerating Cursor rules, and
  keeping the plugin structure consistent. Use when editing SKILL.md files,
  reference files, or plugin manifests; creating a new plugin; or reviewing a
  skill for compliance with authoring standards. Do NOT trigger for general
  coding tasks, security scanning, or platform API queries.
---

# Skill Authoring Guide

This skill documents the rules for creating and maintaining agent skills in
the `stackhawk/agent-skills` repository.

---

## Authoring Rules (Quick Reference)

These are the non-negotiable rules. CI validates them on every PR.

| Rule | Requirement |
|------|-------------|
| SKILL.md length | Body ≤ 500 lines (excluding frontmatter) |
| Frontmatter | `name:`, `version:`, `description:` all required |
| Description | Third person; max 1024 characters |
| Reference files | All linked from SKILL.md; must not link to each other |
| Reference ToC | Required when file > 100 lines |
| Progressive disclosure | Summary + link in SKILL.md; detail in `references/` |

---

## SKILL.md Rules

### Frontmatter

Every SKILL.md must open with a YAML frontmatter block:

```yaml
---
name: <skill-name>          # matches the plugin directory name and symlink folder name
version: <semver>           # kept in sync by bump-version.sh
description: >              # third person; max 1024 characters; describes when to trigger
  ...
---
```

**Description writing rules:**
- Third person ("Guides authoring...", not "I help you author...")
- Opens with what the skill does (verb phrase)
- Includes "Use when" trigger conditions
- Includes "Do NOT trigger for" exclusions
- Max 1024 characters — CI rejects longer descriptions

### Body length

The SKILL.md body (everything after frontmatter) must stay at or under **500 lines**.
Use the progressive disclosure pattern to stay within this limit:
- Keep decision logic, commands, and critical rules in SKILL.md
- Move deep detail to `references/*.md` files and link them from SKILL.md
- Link format: `→ [`references/filename.md`](references/filename.md)`

### What belongs in SKILL.md

- Trigger/skip conditions (when to run, when to stop)
- Step-by-step orchestration logic the agent follows
- Decision tables and critical rules
- Commands the agent runs directly
- Links to reference files (one line per link)

### What belongs in `references/`

- Full command references with all flags
- Pattern tables too large for SKILL.md
- Deep technical detail referenced only in specific situations
- Content > ~30 lines that supports one topic

---

## Reference File Rules

### Linking (critical — enforced by best practices)

- **All** reference files must be linked from SKILL.md directly
- Reference files must **NOT** link to other reference files
- One level deep only: SKILL.md → reference files; references do not link to references
- When a reference file needs to point the reader elsewhere, write "See Step X in SKILL.md"
  rather than linking to another reference file

### Table of Contents

Reference files longer than 100 lines must include a `## Contents` ToC with anchor links
immediately before the first `##` section. Format:

```markdown
## Contents
- [Section Name](#section-name)
- [Another Section](#another-section)

---

## Section Name
```

Shorter files may omit the ToC.

---

## Creating a New Plugin

Follow these steps in order. All are required.

**1. Create directory structure:**
```
plugins/<name>/
  skills/<name>/
    SKILL.md
    references/        # create if needed
  .claude-plugin/
    plugin.json
  .codex-plugin/
    plugin.json
```

**2. Write `SKILL.md`** following the rules above. Use current VERSION file for the
version field (`cat VERSION`).

**3. Create manifests** — copy an existing plugin's `plugin.json` as a template:
```bash
# .claude-plugin/plugin.json and .codex-plugin/plugin.json
# Set name, version (match VERSION file), description, keywords
```

**4. Create symlinks** for platform discovery (use relative paths):
```bash
cd skills/ && ln -s ../plugins/<name>/skills/<name> <name>
cd .opencode/skills/ && ln -s ../../plugins/<name>/skills/<name> <name>
cd .cursor/skills/ && ln -s ../../plugins/<name>/skills/<name> <name>
```

**5. Add Cursor mapping** in `scripts/generate-cursor-rules.sh` MAPPINGS array:
```
"<name>/skills/<name>/SKILL.md|stackhawk-<name>|<cursor description>|<globs>|<alwaysApply>"
```

**6. Add to `.version-bump.json`** — add two entries (one per manifest):
```json
{ "path": "plugins/<name>/.claude-plugin/plugin.json", "field": "version", "type": "json" },
{ "path": "plugins/<name>/.codex-plugin/plugin.json", "field": "version", "type": "json" },
{ "path": "plugins/<name>/skills/<name>/SKILL.md", "field": "version", "type": "yaml-frontmatter" }
```

**7. Bump version** (new skill = `--minor`):
```bash
bash scripts/bump-version.sh --minor
```

**8. Regenerate Cursor rules:**
```bash
bash scripts/generate-cursor-rules.sh
```

**9. Verify idempotency:**
```bash
bash scripts/generate-cursor-rules.sh && git diff cursor/
# → no diff means rules are in sync
```

---

## Updating an Existing Skill

After any edit to `SKILL.md` or `references/*.md`:

1. **Verify line count** (SKILL.md body ≤ 500 lines):
   ```bash
   wc -l plugins/<name>/skills/<name>/SKILL.md
   ```

2. **Verify reference linking** — no reference file links to another reference file:
   ```bash
   grep -rn "\](.*\.md)" plugins/<name>/skills/<name>/references/
   # Any hit means a reference file is linking to another file — remove it
   ```

3. **Regenerate Cursor rules:**
   ```bash
   bash scripts/generate-cursor-rules.sh && git diff cursor/
   ```

4. **Bump version** — include in the same commit as the content change:
   ```bash
   bash scripts/bump-version.sh --patch   # for fixes and content updates
   bash scripts/bump-version.sh --minor   # for new capabilities
   ```

---

## Version Bump Rules

| Change type | Flag |
|-------------|------|
| Bug fix, content correction, typo | `--patch` |
| New skill, new reference file, new capability | `--minor` |
| Breaking change (removed step, changed trigger conditions) | `--major` |

`VERSION` is the single source of truth. `bump-version.sh` reads `.version-bump.json`
and updates all manifests and SKILL.md frontmatter atomically. Never edit version numbers
manually in individual files.

---

## CI Validation

`generate-and-validate.yml` runs on every PR and checks:

- Version consistency across all manifests
- Cursor rules are up to date (no diff after running `generate-cursor-rules.sh`)
- SKILL.md frontmatter has `name:`, `version:`, `description:`

The PR will be blocked if any check fails. Fix by running:
```bash
bash scripts/bump-version.sh --patch    # or --minor/--major
bash scripts/generate-cursor-rules.sh
git add plugins/ cursor/ scripts/ && git commit --amend --no-edit
```
