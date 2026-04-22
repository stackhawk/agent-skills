# StackHawk API Skill for Claude

Security posture reporting and findings analysis powered by the [StackHawk platform API](https://apidocs.stackhawk.com), embedded directly into your Claude agentic workflow.

## What This Does

This plugin teaches Claude how to query the StackHawk platform for security reporting. It authenticates, retrieves findings data across your applications and environments, and presents actionable security posture summaries — helping you understand where your risks are, what changed between scans, and which apps need attention.

```
Question → Authenticate → Query API → Present Results → Suggest Next Actions
```

The skill prefers the [**`hawkop` CLI**](https://docs.stackhawk.com/hawkop/) when it's installed — most operations collapse from a three-call drill-down pipeline into a single `hawkop` command with built-in auth, pagination, and JSON output. When `hawkop` is not available, the skill falls back to raw REST calls using the bundled helper scripts.

## Prerequisites

- A [StackHawk account](https://app.stackhawk.com) (free tier available)
- A StackHawk API key — generate one at **Settings → API Keys**
- **Recommended:** [`hawkop`](https://docs.stackhawk.com/hawkop/) installed and configured (`hawkop init`)
- **Or** `HAWK_API_KEY` set as an environment variable (raw API fallback)
- `jq` installed (used for JSON processing in the raw API path)

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

Never hardcode your API key. Always set it as an environment variable and reference it as `$HAWK_API_KEY` (raw API) or `$HAWKOP_API_KEY` (hawkop in CI/CD) in scripts or configurations.

## Resources

- [HawkOp CLI docs](https://docs.stackhawk.com/hawkop/)
- [StackHawk API Docs](https://apidocs.stackhawk.com)
- [StackHawk Platform](https://app.stackhawk.com)
- [StackHawk Support](https://support.stackhawk.com)

## License

MIT © [StackHawk](https://www.stackhawk.com)
