# App Discovery — Docs-First Source Table

The full discovery workflow lives in `references/scan-planning.md` — see Step 1a in SKILL.md
(per-surface detection, route-inventory derivation, gap recommendations, and the
user-confirmed summary required before the first scan). This file holds the docs-first source
table below, which SKILL.md links to directly and which stands on its own.

## Read the repo's own docs first

Repos usually already describe what they are and how to run them. Check these, in priority
order, and treat what they say as authoritative:

| Source | Typically documents |
|--------|----------------------|
| `AGENTS.md` | run/build/test commands, layout, conventions |
| `CLAUDE.md` | same, written for agents — often the richest source |
| `GEMINI.md`, `.github/copilot-instructions.md` | agent run/build guidance |
| `.cursor/rules/*` | project conventions and setup steps |
| `README*` | quickstart, run command, default host/port |
| `CONTRIBUTING*` | local dev setup, how to run services and tests |
| `docs/` setup / quickstart / development pages | deeper local-run and API detail |

Harvest the **run/start command**, the **local host + port**, the **API style**
(REST/OpenAPI, GraphQL, gRPC, or a plain web app), and any **documented dev/test login or
seed data**. If a file answers a question, don't rediscover it by exploring.
