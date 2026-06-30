# HawkScan Skill for Claude

Dynamic application and API security testing (DAST) powered by [StackHawk HawkScan](https://www.stackhawk.com), embedded directly into your Claude agentic workflow.

## What This Does

This plugin teaches Claude how to act as the security testing orchestrator in an agentic coding loop:

```
Code changes → Configure HawkScan → Run scan → Parse findings → Generate fix tasks → Repeat
```

Claude will automatically:
- Generate or tune `stackhawk.yml` configuration based on your app's stack and auth pattern
- Run HawkScan via CLI (`hawk`) or Docker
- Validate config before burning a full scan run
- Parse scan findings and produce prioritized, actionable fix tasks
- Re-run scans after fixes to confirm remediation

## Prerequisites

- A [StackHawk account](https://app.stackhawk.com) (free tier available)
- A StackHawk API key — generate one at **Settings → API Keys**
- HawkScan CLI (`hawk`) or Docker installed
- `hawk init --browser` run to store credentials locally (for local/agentic use); or `HAWK_API_KEY` set as a CI secret (for pipelines)

## Installation

```bash
# Add the StackHawk marketplace
/plugin marketplace add stackhawk/claude-skills

# Install the HawkScan skill
/plugin install hawkscan@stackhawk
```

## Usage

Once installed, Claude will automatically use the HawkScan skill when you:

- Ask it to scan your app for security issues
- Reference `stackhawk.yml`, `hawkscan`, or DAST
- Ask it to set up security testing in your project or CI pipeline
- Have it fix code — it will proactively suggest running a scan

You can also trigger it explicitly:

> "Set up HawkScan for my Express API and run a scan"

> "My HawkScan auth is failing, help me debug it"

> "Turn these scan findings into fix tasks"

## Supported Configurations

- **App types**: REST/OpenAPI, GraphQL, gRPC, SOAP, standard web apps
- **Auth patterns**: Bearer token, form login, cookie, OAuth2/external IdP, custom scripts
- **Runtimes**: `hawk` CLI, Docker (`stackhawk/hawkscan`)
- **Environments**: Local dev, CI/CD (GitHub Actions, GitLab, etc.)

## Security Note

Never hardcode credentials in `stackhawk.yml`. For local use, `hawk init` stores your API key in `~/.hawk/hawk.properties`. For CI/CD, set `HAWK_API_KEY` as a secret — never inline key values in config files or scripts.

## Resources

- [HawkScan Docs](https://docs.stackhawk.com/hawkscan/)
- [StackHawk CLI Reference](https://docs.stackhawk.com/stackhawk-cli/)
- [Auth Configuration Examples](https://github.com/kaakaww/hawkscan-examples)
- [StackHawk Support](https://support.stackhawk.com)

## License

MIT © [StackHawk](https://www.stackhawk.com)
