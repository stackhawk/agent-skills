# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
