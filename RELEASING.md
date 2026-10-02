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

### Step 5: Sync the Marketplace

Run the release workflow from the new tag. It is manually dispatched, so pushing the tag alone does not start it. The workflow accepts the GitHub Release created in Step 4, re-validates the tag, and pushes the validated marketplace sync directly to its `main` branch.

```bash
gh workflow run release.yml --ref "v$(cat VERSION)"
```

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

The GitHub Actions workflow (`.github/workflows/release.yml`) runs when manually dispatched from an existing release tag:

### Pre-Release Validation

When dispatched from a tag, the workflow:

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

- **Creates a GitHub Release** with the tag as title and changelog section as body if the standalone release script has not already created it
- **Makes the tag and release available** for the marketplace sync; marketplace consumers receive the new version when the sync job pushes to marketplace `main`

If validation fails, the workflow exits before the marketplace sync. Resolve the tag or version mismatch before rerunning it.

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

The `update-marketplace` job in `.github/workflows/release.yml` runs after the GitHub Release is created. It clones [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace), runs that repository's `scripts/sync-agent-skills.py` against the release tag, validates its generated layout, and commits only the sync outputs to marketplace `main`. A rerun for an already synced tag makes no commit. If `main` advances before the push, the job fetches and rebases once, reruns the marketplace tests, then retries the push without force.

The sync script owns all marketplace release outputs:

1. **Claude plugin snapshots and catalog:** It copies the released plugin folders into `plugins/` and writes `.claude-plugin/marketplace.json` with local `./plugins/<name>` sources, so directory validation can inspect each plugin.
2. **Codex and Copilot catalogs and wingman bundle:** It points catalog sources at marketplace paths and writes the Copilot and Codex wingman bundle under `bundles/wingman/`.
3. **Standalone skills:** It rebuilds `skills/` for the [`skills` CLI](https://github.com/vercel-labs/skills), which discovers `SKILL.md` files and ignores marketplace catalogs.

Review the resulting commit on marketplace `main` after the job succeeds. In its checkout, run `claude plugin validate --strict .`, validate each `plugins/<name>` folder, and run `python3 -m unittest discover -s tests`. The release job runs the marketplace tests before pushing. The separate `Marketplace Install Verify` workflow in this repository tests catalog compatibility and standalone skill discovery from local fixtures.

If the workflow fails, inspect the job logs, fix the cause, and rerun it from the same tag. Do not hand-edit generated catalogs, plugin snapshots, or standalone skills.
