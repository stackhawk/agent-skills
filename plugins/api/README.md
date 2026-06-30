# StackHawk API Skill for Claude

Security posture reporting and findings analysis powered by the [StackHawk platform API](https://apidocs.stackhawk.com), embedded directly into your Claude agentic workflow.

## What This Does

This plugin teaches Claude how to query the StackHawk platform for security reporting. It authenticates, retrieves findings data across your applications and environments, and presents actionable security posture summaries — helping you understand where your risks are, what changed between scans, and which apps need attention.

```
Question → Authenticate → Query API via hawk op → Present Results → Suggest Next Actions
```

The skill uses the combined `hawk` CLI (`hawk op …`) — most operations collapse from a three-call drill-down pipeline into a single `hawk op` command with built-in auth, pagination, and JSON output.

## Prerequisites

- A [StackHawk account](https://app.stackhawk.com) (free tier available)
- A StackHawk API key — generate one at **Settings → API Keys**
- The `hawk` CLI installed and initialized via `hawk init --browser` (stores credentials in `~/.hawk/hawk.properties`)
- For CI/CD pipelines: `HAWK_API_KEY` set as an environment variable
- `jq` installed (used for JSON processing in recipes)

## Installation

```bash
# Add the StackHawk marketplace
/plugin marketplace add stackhawk/claude-skills

# Install the StackHawk API skill
/plugin install api@stackhawk
```

## Usage

Once installed, Claude will use the StackHawk API skill when you ask questions like:

> "What's my security posture across all apps?"

> "Show me the findings from the last scan of my payment-api"

> "Which apps haven't been scanned in the last 30 days?"

> "What changed since the last scan of my auth-service?"

## Supported Queries

- **Org-wide security posture summaries** — aggregate findings and severity counts across all applications
- **Per-app findings deep dives** — drill from application → scan → alerts → individual findings
- **Stale app detection** — identify applications that haven't been scanned recently
- **Scan comparison** — surface what changed (new, resolved, or modified findings) between scans
- **Team and environment management** — view apps by team, environment, or environment type

## Security Note

Never hardcode your API key. For local/agentic use, `hawk init` stores credentials locally. For CI/CD, set `HAWK_API_KEY` as a pipeline secret — never inline key values in scripts or configs.

## Resources

- [hawk CLI docs](https://docs.stackhawk.com)
- [StackHawk API Docs](https://apidocs.stackhawk.com)
- [StackHawk Platform](https://app.stackhawk.com)
- [StackHawk Support](https://support.stackhawk.com)

## License

MIT © [StackHawk](https://www.stackhawk.com)
