# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `hawkscan`: `references/scan-policy.md` — the first scan is one broad detected-stack policy run to completion; when several full scans run, the broadest runs last (the last completed scan is the result); follow-up full scans prune tech flags or fix auth/spec rather than raising strength across all plugins; a named org policy attaches only via `app.scanPolicy.name`; hand-built policy traps (`STRENGTH_LOW`/`THRESHOLD_LOW` are protobuf zero values and are silently dropped; stripping `pluginType` drops every passive rule). Evidence: seven headless first-run sessions on hawk 6.4.0 / wingman 2.5.0.
- `hawkscan`: `references/input-vectors.md` — HAR seed (`hawk.spider.har`) for `application/xml` and other non-JSON bodies (the OpenAPI request builder emits JSON for XML operations, which 500s and blocks XXE), `app.openApiConf.customVariables` scoped per resource with the field-name collision caveat, and the rule that active injection rules need a reachable sink.
- `hawkscan`: auth guidance now warns that an `app.authentication.profiles` block **without** `--profile-scan-mode=primary-full` runs only the hidden `BUSINESS_LOGIC` preset (BOLA/BFLA, 2 plugins, 0 general findings) — configure one user, or profiles plus that mode when BOLA/BFLA coverage is the goal and the installed hawk has the flag (builds without it must not use profiles) — and to scan as a non-privileged user or pinned token because an admin scan can mutate its own login.
- `hawkscan`: memory and crash-detection guidance — `--hawk-mem` default (9g), the SIGABRT heap-exhaustion symptom, never shortening `hawk.scan.maxRuleDurationMinutes` to fit memory (it truncates injection rules), and `hawk.scan.crashDetection.action: WARN` for endpoints that block on DNS or shell out.
- `stackhawk-api`: names the 10-plugin cap of `hawk op scan get --detail full` and points at the `hawk scan --json-output` file as the complete list.
- `skill-authoring` skill: changelog update guidance — documents when and how to add CHANGELOG entries for every substantive skill change
- `wingman` umbrella plugin: `/plugin install wingman@stackhawk` installs the default skill set.
- `skills` CLI support: `npx skills add stackhawk/agent-skills-marketplace --all` installs the current GA release for any agent the CLI detects, and `npx skills update` moves to the next release. The CLI discovers SKILL.md files only and ignores marketplace.json, so `release.yml` now vendors the five public skills (`hawkscan`, `stackhawk-api`, `hawkscan-ci`, `stackhawk-data-seed`, `stackhawk-optimize`; namespaced like the wingman Copilot bundle) into the marketplace repo's `skills/` via the new `scripts/generate-marketplace-skills.py`. Previously `npx skills add stackhawk/agent-skills-marketplace` found nothing and `npx skills add stackhawk/agent-skills` installed unversioned `main` plus the maintainer-only `skill-authoring` skill. A `skills-cli` job in `marketplace-install-verify.yml` checks the vendored output.

### Fixed
- `hawkscan` `cli-reference.md`: the `--hawk-mem` example said `2g` while claiming to "increase" memory from a 9g default.

### Changed
- `hawkscan` Phase 0c now runs optimize Setup on **every fresh `stackhawk.yml`**, not only on first app onboarding — reused apps skipped policy setup entirely and every operator hand-built a policy. `optimize` and `platform-model.md` wording updated to match.
- `hawkscan`/`stackhawk-api`: `API_KEY=$HAWK_API_KEY hawk …` is now the documented answer for any non-interactive session (CI, containers, headless agents), not "CI/CD only"; "re-run `hawk init --browser` on a 401" applies to interactive sessions only. Steps that need a person (`hawk perch onboard` via Chrome, the pre-scan confirmation) are marked interactive-only with a one-line headless alternative.
- `stackhawk-optimize`: the GraphQL mapping no longer suggests `app.autoPolicy: true` (it narrows the plugin set and is not a `stackhawk.yml` section on current hawk); keep the broad GraphQL preset for the first scan. Added the hand-built policy traps to the plugin-editing guidance.
- Skills now drive the combined `hawk` binary (`hawk op …`); the `api` skill's raw-REST fallback was removed.
- `skill-authoring` moved from `plugins/skill-authoring/` to `.claude/skills/skill-authoring/` (maintainer skill, not a marketplace plugin)
- `.gitignore` updated: `.claude/skills/` is now tracked so contributor skills are version-controlled
- Removed `skill-authoring` from public release paths (`skills/`, `.opencode/skills/`, `.cursor/skills/`) and Cursor rule generation

## [2.5.0]

### Fixed
- `copilot plugin install wingman@stackhawk` reported success but installed zero skills — GitHub Copilot CLI has no plugin-dependency mechanism, so `plugins/wingman/`'s `"dependencies"` field (resolved by Claude Code and Codex) was silently ignored. Added a Copilot-only manifest, `plugins/wingman/.github/plugin/plugin.json`, with `"skills": "./copilot-skills/"`, pointing at a generated bundle of real copies of wingman's four dependency skills (`scripts/generate-wingman-skills.sh`).
- Corrected the documented Copilot install path from `~/.agents/skills/` to `~/.copilot/installed-plugins/`.

### Added
- CI now validates the wingman Copilot bundle (`scripts/test-wingman-skills.sh`) and catches untracked drift in the generated `copilot-skills/` output on every PR and at release time.

### Changed
- The wingman Copilot bundle now namespaces its skill names, so Copilot lists `stackhawk-api` and `stackhawk-optimize` instead of the generic `api` and `optimize`. Only the bundled copies are rewritten — the source skills keep their current names, so Claude Code, Codex, Cursor, Gemini, and OpenCode are unaffected. Note that a per-plugin Copilot install (`copilot plugin install stackhawk-api@stackhawk`) reads the source skill and therefore still lists `api`; unifying that requires renaming the source skills, which changes invocation names on every platform and is deferred to a separate major release.

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
