# Grading

How `scripts/grade.py` scores a cell, and how to author the inputs it
needs: process checks for observational hypotheses, and ground truth for
both grader types.

## Contents
- [Designing process-checks for an observational hypothesis](#designing-process-checks-for-an-observational-hypothesis)
- [Authoring ground truth](#authoring-ground-truth)
- [The observational grader](#the-observational-grader)
- [The task-completion grader](#the-task-completion-grader)
- [Prior art: skillz-benchmark](#prior-art-skillz-benchmark)

---

## Designing process-checks for an observational hypothesis

Process checks are the Stage 1, deterministic half of grading (see
`references/methodology.md` for why both stages exist). `grade.py`'s
`process_checks()` computes them from the parsed transcript alone — no
model call, fully reproducible. Our **worked example — the app-discovery
reframe (skill v2.0.0 → v2.1.0)** — computed 7 signals:

1. `read_agent_docs` — did the agent read repo docs (README, CONTRIBUTING,
   `docs/`, etc.) at all during the run.
2. `docs_before_conclusion` — did that doc-read happen *before* the first
   textual conclusion, not after (ordering matters — an agent that reads
   docs only to double-check a guess it already stated doesn't count).
3. `explored_manifests` — did it read at least one manifest/config file
   (package.json, Dockerfile, go.mod, etc.).
4. `exploration_breadth` — count of distinct files read; a thoroughness
   proxy.
5. `emitted_five_answers` — did the final response include every field the
   prompt asked for.
6. `stayed_read_only` — no guard denial was recorded for this cell.
7. `ran_legacy_command_menu` — did it regress to a superseded pattern the
   change was meant to retire.

**Reference outcome** (that run — 3 apps × 2 arms, 1 run/cell):

| Signal | OLD v2.0.0 | NEW v2.1.0 |
|---|---|---|
| `read_agent_docs` | 1/3 apps | **3/3** |
| `docs_before_conclusion` | 1/3 | **3/3** |
| `exploration_breadth` | 8.7 files | **13.7** |
| `ran_legacy_command_menu` | 1/3 | **0/3** |
| correctness (judge, of 5) | 4.67 | 4.33 |

The reframe moved the docs-first signals decisively (the intended change),
with no correctness regression and no pigeonholing — and the *deterministic*
signals carried the verdict, which is exactly why Stage 1 is the backbone.
That is the shape every benchmark aims for: a clear move on the targeted
metric, nothing else regressed.

When you design process-checks for your own hypothesis, follow the same
shape: each check should be (a) computable by a regex or simple parse over
`tool_calls`/`events`/`final_text` — no judgment calls, (b) named for what
it measures, and (c) directly traceable back to one clause of your Step 1
hypothesis (the "metric to move" or the "must not regress" list). A check
that doesn't map to either is noise — leave it out.

## Authoring ground truth

One `ground-truth/<app>.json` per repo, written by you (the human/agent
author) *before* running either arm, from direct inspection of the repo —
never inferred from what an arm produces. Required shape:

- The answer fields specific to your prompt (for app-discovery:
  `run_command`, `host`, `api_style`, `spa`, `auth`).
- `evidence` — one string per answer field, citing the specific file(s)
  and line-level detail that justify the answer. This is what lets a human
  reviewer (or a future you) audit whether the ground truth itself is
  correct, and it's what the judge is implicitly checked against.
- `app` — the app name, matching its row in `apps.tsv`.

Sample (app-discovery, `miniflux`):

```json
{
  "app": "miniflux",
  "run_command": "docker compose up (requires PostgreSQL) or `make run` against a local Postgres",
  "host": "http://127.0.0.1:8080 (binary/make run); 0.0.0.0:8080 in Docker",
  "api_style": "REST, no served OpenAPI spec; base path /v1/ (plus /fever/, /reader/api/0/)",
  "spa": "no (server-rendered Go templates)",
  "auth": "required — web session cookie; REST API via HTTP Basic or X-Auth-Token header",
  "evidence": {
    "run_command": "Makefile `run` target + contrib/docker-compose/basic.yml",
    "host": "internal/config/options.go LISTEN_ADDR default",
    "api_style": "internal/http/server/routes.go registers /v1/",
    "spa": "internal/ui server-side templates; assets bundled in the binary",
    "auth": "internal/api/api.go validateAPIKeyAuth + validateBasicAuth"
  }
}
```

For task-completion ground truth, the shape is looser since the judge
reads the diff directly — describe the expected vulnerability set and what
"fixed" looks like for each, e.g. `{"app": "...", "vulns": [{"type":
"...", "location": "...", "fix_description": "..."}]}`.

## The observational grader

`grade.py --grader observational` (the default) does two things:
1. Writes `checks.json` from `process_checks()`.
2. Builds a judge prompt (`build_judge_prompt`) containing the ground
   truth, the agent's final text, and an excerpt of its tool calls, and
   sends it to `JUDGE_MODEL` via a bare `claude --print` invocation with no
   skills or MCP servers (`run_judge`). The judge returns JSON: per-field
   `correctness` (correct/partial/wrong) with reasons, an
   `exploratory_score` (0–3), and a `pigeonholed` flag with evidence.
   Result is written to `grade.json`.

## The task-completion grader

`grade.py --grader task-completion` calls `grade_task_completion()`, which
reads `transcript.jsonl` for the agent's final message and `fix.diff`
(truncated to 20000 chars) for the actual code change, then asks the same
skill-blind judge to return JSON with:
- `vulns_found` — count the agent claims to have found/fixed.
- `close_rate` — fraction (0..1) of the expected vulns in ground truth that
  the diff plausibly fixes.
- `coverage_not_reduced` — did the agent avoid weakening the scan (e.g.
  disabling checks or removing routes) just to make findings disappear.
- `app_not_broken` — do the changes look like they keep the app runnable.

This is a judge-based, diff-plus-transcript read — not a real rebuild/rescan
— so treat `close_rate` as directional, same caveat as the observational
judge's `exploratory_score`.

## Prior art: skillz-benchmark

The task-completion grader's three headline metrics —
**detection rate**, **fix close-rate**, and a `broke_app` guard — are not
novel; they mirror the proven approach from `skillz-benchmark`, which
established that judge-based scoring of "did it find the thing, did it fix
the thing, did it break the thing" is a workable substitute for a full
rebuild-and-rescan when grading agent-authored fixes at small n. This
harness's `close_rate` / `coverage_not_reduced` / `app_not_broken` triad is
the same idea, adapted to this repo's cell/transcript/diff artifact shapes.
