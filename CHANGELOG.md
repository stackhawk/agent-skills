# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
