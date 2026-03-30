# StackHawk Skills for Claude

**Your AI coding agent is also your security team.**

StackHawk skills teach Claude to find security vulnerabilities as you build, report your security posture across applications, and help you fix what it finds — all without leaving your workflow. No context switching, no tickets to another team. Your agent scans, reports, and remediates.

Works with [Claude Code](https://docs.anthropic.com/en/docs/claude-code), the Claude desktop app, and anywhere Claude skills are supported.

---

## Two Skills, One Security Workflow

### [hawkscan](./plugins/hawkscan/) — Scan & Fix

Embeds [HawkScan](https://www.stackhawk.com) DAST scanning directly into your coding loop. Claude configures the scanner, runs it against your live app, parses the findings, and generates prioritized fix tasks — then re-scans to confirm the fix worked.

```
Code changes → Configure HawkScan → Run scan → Parse findings → Fix → Re-scan
```

**Use it when:** you're building features, finishing a PR, or setting up security testing for a new project.

### [api](./plugins/api/) — Report & Analyze

Queries the StackHawk platform API to give you a picture of your security posture across all your applications. Claude authenticates, pulls findings data, and presents actionable summaries.

```
Question → Authenticate → Query API → Present Results → Suggest Next Actions
```

**Use it when:** you want to know what needs attention, what changed since the last scan, or which apps are falling behind.

---

## Quick Start

**1. Get your API key**

Sign up or log in at [app.stackhawk.com](https://app.stackhawk.com), go to **Settings → API Keys**, and create a key.

```bash
export HAWK_API_KEY=hawk.xxxxxxxxxxxx.xxxxxxxxxxxx
```

**2. Install the skills**

```bash
# Add the StackHawk marketplace
/plugin marketplace add stackhawk/claude-skills

# Install both skills (or just the one you need)
/plugin install hawkscan@stackhawk
/plugin install api@stackhawk
```

**3. Try it**

```
> "Scan my API for security vulnerabilities"

> "What's my security posture across all apps?"
```

---

## What You Can Do

### Scanning Workflows (hawkscan skill)

| Say this... | Claude will... |
|-------------|---------------|
| "Set up HawkScan for my Express API" | Generate a `stackhawk.yml` config based on your stack |
| "Scan my app for security issues" | Validate config, run `hawk scan`, parse findings |
| "Turn these scan findings into fix tasks" | Prioritize by severity, generate actionable fix guidance |
| "I'm finishing up this feature" | Proactively suggest a security scan before you merge |
| "My HawkScan auth is failing" | Debug your authentication configuration |
| "Set up HawkScan in my CI pipeline" | Generate CI-specific config with commit tagging |

### Reporting Workflows (api skill)

| Say this... | Claude will... |
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

These are [Claude skills](https://docs.anthropic.com/en/docs/claude-code) — they teach Claude domain-specific knowledge through structured markdown files. No runtime dependencies are installed. No code runs in the background.

- **Skill files** define step-by-step workflows with decision logic (assess → configure → execute → parse → act)
- **Reference files** provide endpoint catalogs, config patterns, and pre-built recipes loaded on demand
- The hawkscan skill calls the `hawk` CLI or Docker to run scans
- The api skill calls the StackHawk REST API via `curl` and `jq`

```
plugins/
├── hawkscan/                    stackhawk:hawkscan
│   └── skills/hawkscan/
│       ├── SKILL.md             5-step scan workflow
│       └── references/          CLI flags, config patterns, findings schema, Docker, install
└── api/                         stackhawk:api
    └── skills/api/
        ├── SKILL.md             5-step reporting workflow
        └── references/          Auth flow, endpoint catalog, reporting recipes
```

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
- [StackHawk Platform](https://app.stackhawk.com)
- [StackHawk Support](https://support.stackhawk.com)

---

## Contributing

This repository is maintained by the StackHawk team. To report issues or suggest improvements, [open a GitHub issue](https://github.com/stackhawk/claude-skills/issues) or contact [support@stackhawk.com](mailto:support@stackhawk.com).

## License

MIT © [StackHawk](https://www.stackhawk.com)
