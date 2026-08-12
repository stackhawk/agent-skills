# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `skill-authoring` skill: changelog update guidance — documents when and how to add CHANGELOG entries for every substantive skill change
- `wingman` umbrella plugin: `/plugin install wingman@stackhawk` installs the default skill set.

## [2.5.0]

### Fixed
- `copilot plugin install wingman@stackhawk` reported success but installed zero skills — GitHub Copilot CLI has no plugin-dependency mechanism, so `plugins/wingman/`'s `"dependencies"` field (resolved by Claude Code and Codex) was silently ignored. Added a Copilot-only manifest, `plugins/wingman/.github/plugin/plugin.json`, with `"skills": "./copilot-skills/"`, pointing at a generated bundle of real copies of wingman's four dependency skills (`scripts/generate-wingman-skills.sh`).
- Corrected the documented Copilot install path from `~/.agents/skills/` to `~/.copilot/installed-plugins/`.

### Added
- CI now validates the wingman Copilot bundle (`scripts/test-wingman-skills.sh`) and catches untracked drift in the generated `copilot-skills/` output on every PR and at release time.

### Changed
- Skills now drive the combined `hawk` binary (`hawk op …`); the `api` skill's raw-REST fallback was removed.
- `skill-authoring` moved from `plugins/skill-authoring/` to `.claude/skills/skill-authoring/` (maintainer skill, not a marketplace plugin)
- `.gitignore` updated: `.claude/skills/` is now tracked so contributor skills are version-controlled
- Removed `skill-authoring` from public release paths (`skills/`, `.opencode/skills/`, `.cursor/skills/`) and Cursor rule generation

## [2.1.1] - 2026-07-01

### Fixed
- `scripts/generate-marketplace-catalogs.py`'s `DEFAULT_PLUGINS` publish allowlist was never updated after `hawkscan-ci`, `stackhawk-data-seed`, `stackhawk-optimize`, and `wingman` were added — every release since v1.13.1 silently published only `hawkscan` and `stackhawk-api` to `agent-skills-marketplace`. `/plugin install wingman@stackhawk` returned "not found" even though `wingman` has existed in this repo since #60. All six documented plugins are now published.

## [1.12.0] - 2026-06-11

### Added
- `stackhawk-data-seed` plugin: caller-driven `hawk perch seed` CLI-driving stub with a 3-subcommand flow and a hawk-capability gate that degrades gracefully when unsupported
- hawkscan routing to `stackhawk-data-seed` when backend credentials are missing or scan data is empty (gated on hawk capability)
- Skill-eval harness scaling: compare mode, per-prompt budgets, and an efficiency grader (uv + shared lib)

### Fixed
- `tag-on-merge` workflow now checks the **remote** for an existing tag (`git ls-remote`) instead of the local clone. `actions/checkout` does a shallow fetch without tags, so the prior local `git rev-parse` guard never matched and the step failed at `git push` when `VERSION` was unchanged

## [1.6.2] - 2026-05-21

### Added
- Windows PowerShell installer (`scripts/install.ps1`) for user-level skill installation on Cursor and Copilot
- GH tag-based release workflow (`.github/workflows/release.yml`) — validates all version fields match tag, creates GH Release from CHANGELOG section
- `.version-bump.json` — canonical manifest of all version-bearing files; `bump-version.sh` now reads from it
- `RELEASING.md` — full release runbook: bump → CHANGELOG → tag → GH Release → marketplace PR
- `version:` field in SKILL.md frontmatter for all plugins
- CI best-practices checks: SKILL.md name/description format, 500-line body warning, Windows path detection (Anthropic spec)
- CI marketplace version validation: `.claude-plugin/marketplace.json` plugin-array versions checked against VERSION
- hawk v5.5.11+ preflight check with hard stop and upgrade instructions
- One-scan-at-a-time guard and rescan-as-default in hawkscan skill
- High-iteration findings reference (CSP, CORS, Auth, Headers)
- `hawk config show` recipe fetching replaces inline auth config (requires hawk v5.5.11+)

### Fixed
- `bump-version.sh` now handles JSON, YAML frontmatter, and raw file types atomically
- Root `.codex-plugin/plugin.json` added to CI manifest validation loop (was missing)
- Source validation and safe glob count in `install.ps1`

---

## [1.4.0] - 2026-05-01

### Added
- Phase 0 app setup: agents now create or locate a StackHawk app before scanning (`hawk app create` flow)
- Repo-linking reference: agents can link apps to GitHub/GitLab/Bitbucket repos via the API
- Tech-flags reference: agents detect framework/language from project files and set technology flags on apps
- Real download URLs for hawkscan and hawkop — agents can now install both CLIs without visiting docs
- API triage guidance in false-positives reference so agents know when to triage vs fix vs suppress
- `HAWK_AGENT` environment detection in the autonomous scan loop

### Fixed
- `excludePaths` scope clarified — scanner stays pinned to the configured host; external domains never needed
- `failureThreshold` placement corrected — belongs under `hawk:`, not `app:`
- `--note` placeholder simplified for triage commands

---

## [1.3.0] - 2026-04-23

### Added
- Platform model reference: full Org → App → Env → Scan hierarchy, triage state machine, and agent decision trees
- `hawk rescan --scan-id` documented for fast fix verification in the agentic loop (avoids full re-scan)
- Step 4.5 added to autonomous loop: agents filter findings by triage state before attempting fixes
- App/env existence checks in Step 1 so agents reuse existing apps rather than creating duplicates
- OpenCode plugin discovery support (`.opencode/skills/` symlinks)

### Fixed
- Triage state names corrected to match `FindingStatus` proto (`false-positive`, `accepted-risk`, etc.)

---

## [1.2.0] - 2026-04-22

### Changed
- API skill now prefers `hawkop` CLI over raw REST calls when installed; falls back to `curl`+`jq` otherwise
- Added `hawkop-shortcuts.md` reference: user intent → single `hawkop` command cheat sheet

---

## [1.1.0] - 2026-04-21

### Added
- Per-pattern auth reference files under `references/auth/` (usernamePassword, oauth, script, externalCommand, external) — previously all in one large file

### Fixed
- External auth YAML shape corrected in hawkscan skill references

---

## [1.0.1] - 2026-04-14

### Added
- Git commit SHA and branch tags (`_STACKHAWK_GIT_COMMIT_SHA`, `_STACKHAWK_GIT_BRANCH`) added to scan config so scans are traceable in the platform

### Fixed
- Hook JSON output aligned with Claude Code expected schema (hooks were silently failing)

---

## [1.0.0] - 2026-04-13

### Added
- HawkScan DAST scanning skill with autonomous scan-fix-rescan loop
- StackHawk API reporting skill for security posture and findings analysis
- Auto-trigger hooks for Claude Code and Codex (SessionStart, PostToolUse, Stop)
- Platform-native autonomous behavior for Cursor (alwaysApply), Copilot, Gemini
- Cross-platform hook runner supporting Windows and Unix
- Multi-platform distribution: Claude Code, Codex, Gemini CLI, GitHub Copilot, Cursor
- False positives reference guide for handling accepted risk
- Version bump script (`scripts/bump-version.sh`) for all platform manifests
- Release script (`scripts/release.sh`) with safety checks and GitHub Release creation
- Install script (`scripts/install.sh`) for Cursor and Copilot manual setup
- CI validation for SKILL.md frontmatter, manifest versions, JSON syntax, and Cursor rules

### Platforms
- **Claude Code** — Full plugin with hooks (SessionStart, PostToolUse, Stop)
- **Codex** — Full plugin with hooks
- **Cursor** — Generated .mdc rules (main hawkscan rule: alwaysApply)
- **GitHub Copilot** — Symlink-based skill discovery
- **Gemini CLI** — Extension with autonomous trigger description
