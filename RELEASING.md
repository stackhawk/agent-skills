# Releasing Agent Skills

This guide covers the release process for the agent-skills repository. Releases follow [Semantic Versioning](https://semver.org/) and are published to GitHub as annotated tags and releases.

## Prerequisites

Before releasing, ensure:

- **`gh` CLI installed** — Required for creating GitHub Releases
  ```bash
  brew install gh  # macOS
  # or visit https://cli.github.com for other platforms
  ```
- **On `main` branch** — All releases must be tagged from `main`
  ```bash
  git checkout main
  git pull origin main
  ```
- **Clean working tree** — No uncommitted changes or staged files
  ```bash
  git status  # should show "working tree clean"
  ```

## Standard Release Flow

### Step 1: Bump the Version

Choose the version bump based on the changes:

- **`--patch`** for bug fixes (1.5.4 → 1.5.5)
- **`--minor`** for new skills or features (1.5.4 → 1.6.0)
- **`--major`** for breaking changes (1.5.4 → 2.0.0)

```bash
bash scripts/bump-version.sh --patch
```

This updates all version-bearing files:
- `VERSION`
- `.claude-plugin/marketplace.json`
- `.codex-plugin/plugin.json`
- `gemini-extension.json`
- `plugins/hawkscan/.claude-plugin/plugin.json`
- `plugins/hawkscan/.codex-plugin/plugin.json`
- `plugins/api/.claude-plugin/plugin.json`
- `plugins/api/.codex-plugin/plugin.json`
- `plugins/hawkscan/skills/hawkscan/SKILL.md`
- `plugins/api/skills/api/SKILL.md`

### Step 2: Update CHANGELOG.md

Add an entry for the new version following [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [1.5.5] - 2026-05-21

### Added
- (If new features)

### Fixed
- (If bugs fixed)

### Changed
- (If existing behavior changed)
```

Place this entry at the top, above the previous releases. Use ISO date format (YYYY-MM-DD).

### Step 3: Commit the Changes

```bash
git add VERSION CHANGELOG.md .claude-plugin/marketplace.json .codex-plugin/plugin.json gemini-extension.json plugins/
git commit -m "chore: bump version to $(cat VERSION)"
git push origin main
```

The commit message should follow the format: `chore: bump version to X.Y.Z`

### Step 4: Create the Release

Run the release script, which performs pre-release validation and creates both a git tag and GitHub Release:

```bash
bash scripts/release.sh
```

This script:
1. Validates the working tree is clean
2. Confirms you're on the `main` branch
3. Checks that the tag doesn't already exist
4. Ensures Cursor rules are up to date
5. Verifies version consistency across all manifests
6. Creates an annotated git tag: `v{version}`
7. Pushes the tag to origin
8. Creates a GitHub Release with the changelog section as the release notes

## Pre-Release Versions

For pre-release versions (beta, release candidate), use semantic versioning with a pre-release suffix:

```bash
bash scripts/bump-version.sh 1.5.5-beta.1
bash scripts/bump-version.sh 1.6.0-rc.1
```

Pre-release versions:
- Are included in version sort order (1.5.5-beta.1 < 1.5.5)
- Are **not** automatically discovered by consumers unless they explicitly opt in
- Follow the pattern `X.Y.Z-<identifier>.<number>` (e.g., `-beta.1`, `-rc.2`, `-alpha.3`)

Consumers can opt in to pre-releases by configuring their platform to accept pre-release versions.

## Dry Run

Before committing to a release, validate the entire flow without creating tags or releases:

```bash
bash scripts/release.sh --dry-run
```

Output:
```
=== DRY RUN MODE ===

Preparing release: vX.Y.Z

All pre-release checks passed.

DRY RUN: Would create tag 'vX.Y.Z' and GitHub Release.
DRY RUN: Run without --dry-run to execute.
```

Use this to catch issues (version mismatches, Cursor rule drift, missing CHANGELOG entries) before publishing.

## Consumer Cache Clearing

After a release is published, consumers may see their plugin caches. To force a refresh:

```bash
rm -rf ~/.claude/plugins/cache/
```

Consumers should clear their cache after pulling a new version. This is documented in their respective plugin configuration docs.

## What the Release Workflow Does

The GitHub Actions workflow (`.github/workflows/release.yml`) runs automatically when a `v*.*.*` tag is pushed:

### Pre-Release Validation

When triggered by a tag push, the workflow:

1. **Extracts the version from the tag** — e.g., `v1.5.5` → `1.5.5`
2. **Validates VERSION file matches the tag** — Ensures `VERSION` file contains exactly the tag version
3. **Validates all manifest versions match the tag** — Checks:
   - `.claude-plugin/marketplace.json`
   - `.codex-plugin/plugin.json`
   - `gemini-extension.json`
   - `plugins/hawkscan/.claude-plugin/plugin.json`
   - `plugins/hawkscan/.codex-plugin/plugin.json`
   - `plugins/api/.claude-plugin/plugin.json`
   - `plugins/api/.codex-plugin/plugin.json`
4. **Validates SKILL.md versions match the tag** — Checks frontmatter `version:` in each skill file
5. **Extracts changelog section** — Pulls the `## [X.Y.Z]` section from CHANGELOG.md for release notes

### GitHub Release Creation

If all validation passes, the workflow:

- **Creates a GitHub Release** with the tag as title and changelog section as body
- **Makes the release available** to marketplace consumers and integrations

If validation fails, the workflow exits with an error and no release is created. Fix the issue locally, amend the commit, force-push if needed, and retry.

## Recovering from a Bad Tag

If you create a tag and the release workflow fails (or you spot an issue before publishing):

### Delete the local tag:
```bash
git tag -d vX.Y.Z
```

### Delete the remote tag:
```bash
git push origin --delete vX.Y.Z
```

### Fix the issue locally:
```bash
# Fix VERSION, CHANGELOG, manifests, or SKILL.md files
bash scripts/bump-version.sh X.Y.Z  # re-bump if needed
git add -A
git commit --amend --no-edit
git push origin main --force-with-lease
```

### Retry the release:
```bash
bash scripts/release.sh
```

## Updating the Marketplace Catalog

After a release is published, the [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace) repository's `marketplace.json` should be updated to reference the new tag and commit SHA.

Update entries in that repo's catalog with:

- **`ref`** — The new tag (e.g., `v1.5.5`)
- **`sha`** — The commit SHA of the tag (run `git rev-parse v1.5.5` to get it)
- **`version`** — The version number (e.g., `1.5.5`)

This allows marketplace consumers to discover and install the new version.

### Example update:

```json
{
  "name": "agent-skills",
  "title": "StackHawk Agent Skills",
  "description": "...",
  "ref": "v1.5.5",
  "sha": "abc1234567890def...",
  "version": "1.5.5"
}
```

Submit a PR to the marketplace repo with this update.
