# App Discovery Reference

How to understand a target application before configuring a scan — what it is, how to run
it locally, how to reach its API, and whether it needs auth. Used by Step 1a in SKILL.md.
Prefer the repo's own documentation; explore only to fill gaps; ask the user for whatever
remains. Do not treat any of this as a fixed checklist of commands.

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

## The four answers discovery must produce

From docs, exploration, or the user — be able to state all four before generating config:

1. **Run command + host/port** — the exact way to start the app locally and the URL it
   listens on. Feeds Step 1c ("App running?") and the `host:` in Step 2.
2. **API style + base path** — REST (an OpenAPI/Swagger spec, served or checked in,
   enables `openApiConf`), GraphQL (`graphqlConf`), gRPC (`grpcConf`), or an HTML web app.
   Determines the config shape in Step 2.
3. **SPA or not** — a client-rendered JS front end (React, Vue, Angular, Svelte, Next,
   Nuxt, and the like) requires the Ajax Spider and changes target selection. See the SPA
   rule in Step 1a of SKILL.md.
4. **Auth needed?** — does reaching the real endpoints require a login, and what shape does
   it appear to use (form/session, bearer token, OAuth, custom)? Understand this so you
   scan authenticated when required and don't waste a run against a login wall. **Stop
   there** — picking, configuring, obtaining, or seeding the credential is owned by Step 1c
   / Phase 1c in SKILL.md and the `stackhawk-data-seed` skill. Do not duplicate that here.

## When you can't determine something

Don't stall and don't invent. After reading the docs and a reasonable look through the
repo, ask the user directly for whatever is unresolved — most often the exact start
command, the host/port, or how to log in locally. When file access is limited, skip
exploration and ask up front for all four answers.
