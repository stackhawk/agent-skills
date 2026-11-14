# StackHawk Agent Skills

Your agent writes the code. Nothing checks if it's exploitable.

StackHawk agent skills fix that. Install once and your coding agent can configure security scans, run them against your live app, parse the findings, and fix what it found — all in the same session.

## Try It Free
14 days free, no card required. [auth.stackhawk.com/wingman](https://auth.stackhawk.com/wingman)


**Your AI coding agent is also your security team.**

StackHawk agent skills teach your AI coding agent to find security vulnerabilities as you build, report your security posture across applications, and help you fix what it finds — all without leaving your workflow. No context switching, no tickets to another team. Your agent scans, reports, and remediates.

Works with **Claude Code**, **Codex**, **Gemini CLI**, **GitHub Copilot**, **OpenCode**, **Cursor**, and anywhere the [Agent Skills standard](https://agentskills.io) is supported.

---

## Four Skills, One Security Workflow

### [hawkscan](./plugins/hawkscan/) — Scan & Fix

Embeds [HawkScan](https://www.stackhawk.com) DAST scanning directly into your coding loop. Your agent configures the scanner, runs it against your live app, parses the findings, and generates prioritized fix tasks — then re-scans to confirm the fix worked.

```
Code changes → Configure HawkScan → Run scan → Parse findings → Fix → Re-scan
```

**Use it when:** you're building features, finishing a PR, or setting up security testing for a new project.

### [stackhawk-api](./plugins/api/) — Report & Analyze

Queries the StackHawk platform API to give you a picture of your security posture across all your applications. Your agent authenticates, pulls findings data, and presents actionable summaries.

```
Question → Authenticate → Query API → Present Results → Suggest Next Actions
```

**Use it when:** you want to know what needs attention, what changed since the last scan, or which apps are falling behind.

### [hawkscan-ci](./plugins/hawkscan-ci/) — Wire It Into CI

Once HawkScan works locally, this skill graduates it into your CI/CD pipeline. It detects your CI provider, prompts for trigger and blocking behavior, and writes or patches the workflow file. Provider-agnostic — works with GitHub Actions, GitLab, Jenkins, CircleCI, and more.

```
Local scan works → Detect CI provider → Plan integration → Set secret (CI store or external manager) → Write workflow → Verify and report
```

**Use it when:** you have `stackhawk.yml` working locally and want every PR or scheduled build to scan automatically.

### [stackhawk-data-seed](./plugins/stackhawk-data-seed/) — Seed Scan Data

Drives the `hawk perch seed` flow to generate checked-in seed artifacts — SQL scripts, HTTP fixtures, gRPC stubs, and a credentials handoff file — so HawkScan has real data to reach non-trivial application paths.

```
Analyze repo → Design seed manifest → Generate artifacts → Finalize and hand off to hawkscan
```

**Use it when:** your scan is hitting dead ends because endpoints require specific request data or auth state to reach.

---

## Quick Start

### 1. Get your API key

Sign up or log in at [app.stackhawk.com](https://app.stackhawk.com), go to **Settings → API Keys**, and create a key.

```bash
export HAWK_API_KEY=hawk.xxxxxxxxxxxx.xxxxxxxxxxxx
```

### 2. Install for your platform

Install released builds from [`stackhawk/agent-skills-marketplace`](https://github.com/stackhawk/agent-skills-marketplace). Every release of this repository syncs there with its version stamped in, and one marketplace commit pins one tested release for every agent. This repository (`stackhawk/agent-skills`) is the source: an install from it tracks unreleased `main` and shows the development version (`0.0.0-dev`, or no version at all). Use it only to try a change before it ships ([Development builds](#development-builds-from-this-repository)).

#### Claude Code

```
/plugin marketplace add stackhawk/agent-skills-marketplace
/plugin install wingman@stackhawk      # installs hawkscan + api + data-seed + optimize
```

Advanced — install individually instead:

```
# /plugin install hawkscan@stackhawk
# /plugin install stackhawk-api@stackhawk
# /plugin install hawkscan-ci@stackhawk
# /plugin install stackhawk-data-seed@stackhawk
# /plugin install stackhawk-optimize@stackhawk
```

#### Codex

```
/plugin marketplace add stackhawk/agent-skills-marketplace
/plugin install hawkscan@stackhawk
/plugin install stackhawk-api@stackhawk
/plugin install hawkscan-ci@stackhawk
/plugin install stackhawk-data-seed@stackhawk
/plugin install stackhawk-optimize@stackhawk
```

Or use `/plugin install wingman@stackhawk` to get hawkscan, stackhawk-api, stackhawk-data-seed, and stackhawk-optimize in one install.

#### Gemini CLI

The marketplace has no Gemini extension, so Gemini CLI installs from this repository:

```bash
gemini extensions install https://github.com/stackhawk/agent-skills
```

#### GitHub Copilot

```
copilot plugin marketplace add stackhawk/agent-skills-marketplace
copilot plugin install wingman@stackhawk
```

`wingman` bundles the four default skills (`hawkscan`, `stackhawk-api`,
`stackhawk-data-seed`, `stackhawk-optimize`). Copilot has no plugin-dependency
mechanism, so wingman ships these as bundled copies rather than resolving them.

To add `hawkscan-ci` on top of an existing `wingman` install (it is not a
wingman dependency, but is separately installable):

```
copilot plugin install hawkscan-ci@stackhawk
```

To install skills individually **instead of** `wingman` (do not run this after
installing `wingman` — it duplicates the four skills you already have):

```
copilot plugin install hawkscan@stackhawk
copilot plugin install stackhawk-api@stackhawk
copilot plugin install hawkscan-ci@stackhawk
copilot plugin install stackhawk-data-seed@stackhawk
copilot plugin install stackhawk-optimize@stackhawk
```

Plugins install to `~/.copilot/installed-plugins/stackhawk/<plugin>/`. Confirm
they appear under **GitHub Copilot → Configure Skills** in VS Code.

Skill names differ between the two install paths above. The `wingman` bundle
namespaces its copies, so they list as `hawkscan`, `stackhawk-api`,
`stackhawk-data-seed`, and `stackhawk-optimize`. A per-plugin install reads the
source skill instead, so `stackhawk-api` and `stackhawk-optimize` list as `api`
and `optimize`. Renaming the source skills would change their invocation names
on every platform, so it is deferred to a separate major release.

#### OpenCode

For the released skills, use the [skills CLI](#skills-cli-npx), which supports OpenCode. To
copy the development build instead: skills are auto-discovered from `.opencode/skills/`.
Clone and copy (`-L` dereferences the repo's internal skill symlinks so the copies work
standalone):

```bash
git clone https://github.com/stackhawk/agent-skills.git
mkdir -p .opencode/skills
cp -rL agent-skills/.opencode/skills/* .opencode/skills/

# Global install (all projects):
mkdir -p ~/.config/opencode/skills
cp -rL agent-skills/.opencode/skills/* ~/.config/opencode/skills/
```

Installs `hawkscan`, `stackhawk-api`, `hawkscan-ci`, `stackhawk-data-seed`, and `stackhawk-optimize`.

#### Cursor

Cursor reads the five skills as Agent Skills and loads a skill body only when the skill applies. StackHawk adds three small Cursor-only parts: an always-applied router rule (about 1.2 KB) that names the skills and when each applies, a rule that applies while `stackhawk.yml` is in context, and a stop hook. When a turn ends normally after a code change with no scan, the stop hook asks the agent to run the hawkscan skill, once per conversation. It stays silent after you press stop, after an error, and after its own follow-up turn.

The marketplace gets its Cursor catalog and `install/` from the first release that ships them ([RELEASING.md](RELEASING.md#cursor-distribution-prerequisites)). Until then, use the [development build](#development-builds-from-this-repository).

**Project install** (recommended; Cursor Cloud Agents and automations read only the repository's `.cursor/`). Run the released installer from a clone of the marketplace:

```bash
# macOS / Linux
git clone https://github.com/stackhawk/agent-skills-marketplace.git
bash agent-skills-marketplace/install/install.sh --platform cursor --target .
```

```powershell
# Windows
git clone https://github.com/stackhawk/agent-skills-marketplace.git
.\agent-skills-marketplace\install\install.ps1 -Platform cursor -Target .
```

This installs the skills into `.cursor/skills/`, `stackhawk.mdc` and `stackhawk-config.mdc` into `.cursor/rules/`, and `.cursor/hooks/stackhawk-stop.sh` with one entry merged into `.cursor/hooks.json`. Your other rules, skills and hooks stay. To upgrade, run the installer again: it replaces only StackHawk files, and it removes the generated rules and the `.cursor/hooks/stop.sh` hook that older versions installed.

**User-level install** (every project on this machine): give your home directory as the target (`--target ~`; on Windows, leave out `-Target`). This installs the skills into `~/.cursor/skills/` and the stop hook into `~/.cursor/hooks.json`. Cursor has no file-based user rules, so for the router rule use a project install.

**Team marketplace:** a Cursor team admin can import `stackhawk/agent-skills-marketplace` as a team marketplace. Its Cursor catalog lists the six plugins; `wingman` installs from `bundles/wingman/`, which bundles its four skills, and `hawkscan` from `cursor-plugins/hawkscan/`. Enable `wingman` or the separate plugins, not both: `hawkscan` and `wingman` each carry the router rule and the stop hook.

**One Cursor channel per project.** A project install and a Cursor plugin (`hawkscan` or `wingman`) each bring their own router rule and stop hook, so use one of them in a project, not both. Cursor does not merge two channels, and the installers do not look for a Cursor plugin. A Claude Code install can stay: Cursor imports Claude Code plugins from `~/.claude`, but the StackHawk Claude Code plugins carry no Cursor rule, and their hooks do nothing when Cursor runs them. Cursor then lists the StackHawk skills of that Claude Code install next to those of the Cursor channel. In a headless run (`-p`), the Cursor CLI (2026.11.11) loads a plugin's skills but does not give its rules to the agent, and it runs stop hooks only in interactive sessions. For the router rule in headless runs, use a project install.

The stop hook is a bash script. On Windows, Cursor needs bash (for example Git for Windows) to run it. The generated rules in `cursor/.cursor/rules/` are deprecated: the installers no longer copy them, and `cursor/` will be removed in the next major release.

#### skills CLI (npx)

Works with any agent the [`skills` CLI](https://github.com/vercel-labs/skills) supports. One command installs the current GA release for every agent it detects:

```bash
npx skills add stackhawk/agent-skills-marketplace --all
```

Add `-g` to install globally (every project) instead of into the current one. To move to the next release later (the CLI re-fetches the marketplace repo and re-copies changed skills; this update path is expected from the CLI source and is checked after each release):

```bash
npx skills update
```

Skill names are the namespaced ones: `hawkscan`, `stackhawk-api`, `hawkscan-ci`, `stackhawk-data-seed`, and `stackhawk-optimize`. Install from `stackhawk/agent-skills-marketplace`, not this repo — the marketplace carries the released skills, while this repo's `main` is unreleased work.

**Skills only, no hooks.** The `skills` CLI installs `SKILL.md` and `references/` for each skill. It does not install the hawkscan plugin's hooks, so the automatic scan after a code change does not fire. Claude Code, Codex, and Copilot users who want the hooks should install the plugin instead — the slash commands above, or the scriptable form:

```bash
# Claude Code (no global install needed)
npx @anthropic-ai/claude-code plugin marketplace add stackhawk/agent-skills-marketplace
npx @anthropic-ai/claude-code plugin install wingman@stackhawk

# Codex
codex plugin marketplace add stackhawk/agent-skills-marketplace
codex plugin add hawkscan@stackhawk

# GitHub Copilot
copilot plugin marketplace add stackhawk/agent-skills-marketplace
copilot plugin install wingman@stackhawk
```

#### Development builds from this repository

This repository is also a Claude Code, Codex and Cursor marketplace. Its installs track unreleased `main`: use them to test a change before it ships, not for everyday use.

```bash
# Claude Code (and Codex): the source catalogs
/plugin marketplace add stackhawk/agent-skills
/plugin install wingman@stackhawk

# Cursor: a project install, or one plugin folder in the CLI
git clone https://github.com/stackhawk/agent-skills.git
bash agent-skills/scripts/install.sh --platform cursor --target .     # Windows: .\agent-skills\scripts\install.ps1 -Platform cursor -Target .
cursor-agent --plugin-dir agent-skills/cursor-plugins/wingman
```

The Claude and Codex catalogs list `plugins/hawkscan` and `plugins/wingman`, which carry no Cursor file. Only the Cursor catalog (`.cursor-plugin/marketplace.json`) lists `cursor-plugins/hawkscan` and `cursor-plugins/wingman`, the Cursor-only plugins with their own copies of the skills, the router rule and the stop hook. The Cursor app and the Cursor CLI import Claude Code plugins, so a Claude Code install gives Cursor its skills, no rule, and hooks that do nothing in Cursor. Every other plugin serves both catalogs from its `plugins/<name>` folder.

### 3. Try it

```
> "Scan my API for security vulnerabilities"

> "What's my security posture across all apps?"
```

---

## What You Can Do

### Scanning Workflows (hawkscan skill)

| Say this... | Your agent will... |
|-------------|---------------|
| "Set up HawkScan for my Express API" | Generate a `stackhawk.yml` config based on your stack |
| "Scan my app for security issues" | Validate config, run `hawk scan`, parse findings |
| "Turn these scan findings into fix tasks" | Prioritize by severity, generate actionable fix guidance |
| "I'm finishing up this feature" | Proactively suggest a security scan before you merge |
| "My HawkScan auth is failing" | Debug your authentication configuration |
| "Set up HawkScan in my CI pipeline" | Generate CI-specific config with commit tagging |

### Reporting Workflows (api skill)

| Say this... | Your agent will... |
|-------------|---------------|
| "What's my security posture?" | Pull untriaged findings across all apps, present as a summary table |
| "Show me findings for payment-api" | Drill down: scan → alerts → findings with severity, CWE, paths |
| "Which apps haven't been scanned recently?" | Flag stale apps with no scan in 30+ days |
| "What changed since the last scan?" | Diff two scans, show new and resolved findings |

---

## Supported Configurations

**API & App Types:** REST/OpenAPI, GraphQL, gRPC, SOAP, JSON-RPC, standard web apps

**Authentication Patterns:** Bearer token injection, form login (username/password), cookie sessions, OAuth2/external IdP (Auth0, Okta, Cognito), external command, custom scripts

**Scan Runtimes:** `hawk` CLI (recommended for local/agentic use), Docker (`stackhawk/hawkscan`)

**Environments:** Local development, CI/CD (GitHub Actions, GitLab CI, Jenkins, etc.)

---

## How It Works

These are [Agent Skills](https://agentskills.io) — they teach AI coding agents domain-specific knowledge through structured markdown files. No runtime dependencies are installed. No code runs in the background.

- **Skill files** define step-by-step workflows with decision logic (assess → configure → execute → parse → act)
- **Reference files** provide endpoint catalogs, config patterns, and pre-built recipes loaded on demand
- The hawkscan skill calls the `hawk` CLI or Docker to run scans
- The api skill calls the StackHawk REST API via `curl` and `jq`

### Repository Structure

```
plugins/
├── hawkscan/                    HawkScan DAST scanning (no Cursor files)
│   ├── hooks/                   Claude Code hooks (they do nothing when Cursor runs them)
│   └── skills/hawkscan/
│       ├── SKILL.md             scan workflow
│       └── references/          CLI flags, config patterns, findings schema, Docker, install
├── api/                         StackHawk API reporting
│   └── skills/api/
│       ├── SKILL.md             reporting workflow
│       └── references/          auth flow, endpoint catalog, reporting recipes
├── hawkscan-ci/                 CI/CD pipeline integration
│   └── skills/hawkscan-ci/
│       ├── SKILL.md             CI wiring workflow
│       └── references/          execution shapes, app startup, failure semantics
├── stackhawk-data-seed/         Scan data seeding
│   └── skills/stackhawk-data-seed/
│       └── SKILL.md             hawk perch seed workflow
├── optimize/                    Scan optimization
└── wingman/                     Umbrella: Claude Code dependencies, Copilot and Codex copies (no Cursor files)
cursor-src/                      Cursor router and config rules, Cursor stop hook (hand-written; no catalog lists it)
cursor-plugins/hawkscan/         Cursor-only hawkscan (generated; only the Cursor catalog lists it)
cursor-plugins/wingman/          Cursor-only wingman (generated; only the Cursor catalog lists it)
skills/                          Symlinks for Gemini/Copilot discovery
cursor/                          Generated Cursor .mdc rules (deprecated; not installed)
scripts/generate-cursor-adapter.py  Builds the Cursor plugin manifests and cursor-plugins/
scripts/measure-cursor-context.py   Measures the Cursor context load of an install
scripts/install.sh               Installer for Cursor and Copilot (macOS/Linux)
scripts/install.ps1              Installer for Cursor and Copilot (Windows)
scripts/generate-marketplace-catalogs.py   Builds local install verification catalogs
scripts/generate-marketplace-skills.py     Builds local skills CLI verification copies
scripts/export-marketplace.py      Exports (or --verify checks) the release payload the marketplace publishes
scripts/check-marketplace-layout.py  Checks that payload and the synced marketplace
scripts/cursor-hook-probe.py       Runs one plugin hook as Cursor runs it (used by the layout check)
```

Released plugins and skills are published through [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace). The release exports the payload of its tag (Claude plugin snapshots, the wingman bundle, the Cursor-only hawkscan, the Cursor catalog and installers), and the marketplace sync script publishes it, generates platform catalogs, and vendors standalone skills for `npx skills add`. The release workflow validates the sync and pushes it to marketplace `main`.

### Platform Support

| Platform | Install Method | Skills Available |
|----------|---------------|-----------------|
| skills CLI (any agent) | `npx skills add stackhawk/agent-skills-marketplace --all` | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |
| Claude Code | `/plugin install` | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |
| Codex | `/plugin install` | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |
| Gemini CLI | `gemini extensions install` | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |
| GitHub Copilot | `copilot plugin install wingman@stackhawk` (or per-plugin) | hawkscan, stackhawk-api, stackhawk-data-seed, stackhawk-optimize (+ hawkscan-ci via per-plugin install) |
| OpenCode | Copy to `.opencode/skills/` | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |
| Cursor | `install.sh --platform cursor` (or a Cursor plugin) | hawkscan, stackhawk-api, hawkscan-ci, stackhawk-data-seed, stackhawk-optimize |

---

## Prerequisites

| Requirement | For scanning | For reporting |
|-------------|:---:|:---:|
| [StackHawk account](https://app.stackhawk.com) (free tier available) | Required | Required |
| `HAWK_API_KEY` environment variable | Required | Required |
| [`hawk` CLI](https://docs.stackhawk.com/stackhawk-cli/) or Docker | Required | — |
| [`jq`](https://jqlang.github.io/jq/) | — | Required |
| A running application to scan | Required | — |

---

## Security

Never hardcode your `HAWK_API_KEY` in config files or scripts. Always use environment variables:

```bash
# Good
export HAWK_API_KEY=hawk.xxxxxxxxxxxx.xxxxxxxxxxxx

# Bad — never do this
# api_key: hawk.xxxxxxxxxxxx.xxxxxxxxxxxx  ← in stackhawk.yml
```

The hawkscan skill enforces `${HAWK_API_KEY}` interpolation in all generated configs. The api skill stores tokens in shell variables only — never written to disk.

---

## Resources

- [HawkScan Documentation](https://docs.stackhawk.com/hawkscan/)
- [StackHawk CLI Reference](https://docs.stackhawk.com/stackhawk-cli/)
- [StackHawk API Reference](https://apidocs.stackhawk.com)
- [Auth Configuration Examples](https://github.com/kaakaww/hawkscan-examples)
- [Agent Skills Specification](https://agentskills.io)
- [StackHawk Platform](https://app.stackhawk.com)
- [StackHawk Support](https://support.stackhawk.com)

---

<!-- eval-badges:start -->
<!-- generated by publish-eval-badges.yml from v1.13.1 - do not edit by hand -->
## Eval Results

Skill eval pass rates at the latest release, broken down by skill. Each badge is one agent (tool × model); the score is the deterministic pass rate across that skill's eval prompts.

### hawkscan

> Configures HawkScan, runs StackHawk against your app, fixes the vulnerabilities it finds, and rescans to verify.

[![hawkscan · claude-code · haiku-4-5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fclaude-code%2Fclaude-haiku-4-5-20251001.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan · claude-code · opus-4-7](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fclaude-code%2Fclaude-opus-4-7.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan · claude-code · sonnet-4-6](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fclaude-code%2Fclaude-sonnet-4-6.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan · codex · gpt-5.5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fcodex%2Fgpt-5.5.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan · codex · o3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fcodex%2Fo3.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan · agy · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fagy%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan · cursor · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fcursor%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  

### api

> Queries the StackHawk platform API for findings, scan history, and security posture across your apps.

[![api · claude-code · haiku-4-5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fclaude-code%2Fclaude-haiku-4-5-20251001.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![api · claude-code · opus-4-7](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fclaude-code%2Fclaude-opus-4-7.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![api · claude-code · sonnet-4-6](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fclaude-code%2Fclaude-sonnet-4-6.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![api · codex · gpt-5.5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fcodex%2Fgpt-5.5.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![api · codex · o3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fcodex%2Fo3.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![api · agy · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fagy%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![api · cursor · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fapi%2Fcursor%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  

### stackhawk-data-seed

> Sets up checked-in seed data so authenticated scans can reach non-trivial application paths.

[![stackhawk-data-seed · claude-code · haiku-4-5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fclaude-code%2Fclaude-haiku-4-5-20251001.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![stackhawk-data-seed · claude-code · opus-4-7](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fclaude-code%2Fclaude-opus-4-7.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![stackhawk-data-seed · claude-code · sonnet-4-6](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fclaude-code%2Fclaude-sonnet-4-6.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![stackhawk-data-seed · codex · gpt-5.5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fcodex%2Fgpt-5.5.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![stackhawk-data-seed · codex · o3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fcodex%2Fo3.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![stackhawk-data-seed · agy · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fagy%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![stackhawk-data-seed · cursor · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fstackhawk-data-seed%2Fcursor%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  

### hawkscan-ci

> Wires HawkScan into your CI/CD pipeline — detects the provider and writes the workflow file.

[![hawkscan-ci · claude-code · haiku-4-5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fclaude-code%2Fclaude-haiku-4-5-20251001.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan-ci · claude-code · opus-4-7](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fclaude-code%2Fclaude-opus-4-7.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan-ci · claude-code · sonnet-4-6](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fclaude-code%2Fclaude-sonnet-4-6.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan-ci · codex · gpt-5.5](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fcodex%2Fgpt-5.5.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml) [![hawkscan-ci · codex · o3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fcodex%2Fo3.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan-ci · agy · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fagy%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  
[![hawkscan-ci · cursor · default](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan-ci%2Fcursor%2Fdefault.json)](https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml)  

<!-- eval-badges:end -->

## Claude directory validation

This repository is the source for the plugins submitted through the versioned `stackhawk/agent-skills-marketplace` repository. Validate each source plugin folder with `claude plugin validate --strict plugins/<folder>` before releasing it to the marketplace. The directory portal also checks requirements that this local command does not, including a plugin README of at least 40 words and a license. See [Anthropic's plugin pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist) and validate the released marketplace copy in the portal before submission.

## Contributing

This repository is maintained by the StackHawk team. To report issues or suggest improvements, [open a GitHub issue](https://github.com/stackhawk/agent-skills/issues) or contact [support@stackhawk.com](mailto:support@stackhawk.com).

## License

MIT © [StackHawk](https://www.stackhawk.com)

---
