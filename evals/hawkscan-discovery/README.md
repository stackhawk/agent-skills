# HawkScan App-Discovery Eval

A **pulse** on the hawkscan skill's app-discovery flow (SKILL.md Step 1a): does the
current skill guide an agent to correctly understand a real application before it
configures a scan?

This is an **eval, not a benchmark.** It runs a single arm — the current skill — against
real repos and grades the result against a hand-built answer key, to keep a pulse on
discovery health over time. (Blind A/B benchmarking of a skill *change*, OLD vs NEW, is a
separate concern that lives in `stackhawk/agent-skills-devkit`.)

## What it does

For each repo in `apps.tsv`:

1. Clone it fresh into an isolated working dir.
2. Run the current hawkscan skill headless (`claude --print`) with **cwd = the cloned
   app** and a **read-only guard** (`scripts/guard.py`) — the agent can read/grep/glob but
   cannot write, start the app, scan, push, or reach a non-local host. cwd is the clone and
   never the suite dir, so the agent can never see the answer keys.
3. The agent ends with a `DISCOVERY:` block stating the six factors.
4. Grade two ways (`scripts/grade.py`):
   - **Deterministic process-checks** (no model): read docs first? explored manifests?
     exploration breadth? emitted all answers? stayed read-only? fell back to the old
     grep/node checklist? See `process-checks.json`.
   - **Skill-blind judge** (`claude --print`, no skills/tools, blind to which skill version
     produced the output) scores each factor against the answer key: correct/partial/wrong.
5. `scripts/report.py` writes a per-repo scorecard and a pass/fail pulse.

## The six graded factors

Straight from `plugins/hawkscan/skills/hawkscan/references/app-discovery.md` (the four
answers discovery must produce) plus **technology**:

`technology`, `run_command`, `host` (+ running port), `api_style` (+ base path), `spa`, `auth`.

## Repos

Four real production apps mirrored in the `stackhawk-research` org, one per API style with
no duplicate language/framework stack:

| repo | API style | stack |
|---|---|---|
| firefly-iii | REST + OpenAPI | PHP / Laravel |
| wikijs | GraphQL | JS (Node/Apollo) + Vue |
| memos | gRPC | Go + React |
| dawarich | server-rendered (also a REST/OpenAPI API) | Ruby / Rails |

Answer keys with evidence citations live in `answer-keys/`.

## Run it

```bash
export CLAUDE_CODE_OAUTH_TOKEN=...   # or ANTHROPIC_API_KEY
cd evals/hawkscan-discovery
scripts/run.sh --dry-run             # list cells, execute nothing
scripts/run.sh                       # full run: clone, run, grade, report
NO_JUDGE=1 scripts/run.sh            # deterministic process-checks only (no judge cost)
```

Output lands in `runs/<timestamp>/report.md`.

## Notes / limitations

- One run per repo; directional pulse, not a statistical result.
- Answer keys are author-verified against pinned commits; re-verify when bumping a pin
  (`apps.tsv`). Mirrors carry no release tags, so pins are commit SHAs.
- Cloning `stackhawk-research` (a separate org) from CI needs a token with read access to
  that org.
