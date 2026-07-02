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
`references/methodology.md` for why both stages exist) — computed from the
parsed transcript alone, no model call, fully reproducible. They come in two
layers:

**1. A generic core (`grade.py`, hypothesis-agnostic).** These apply to almost
any observational benchmark, so they live in core and you get them for free:

- `read_agent_docs` — did the agent read repo docs (README, CONTRIBUTING,
  `AGENTS.md`/`CLAUDE.md`, `docs/`, etc.) at all.
- `exploration_breadth` — count of distinct files read; a thoroughness proxy.
- `emitted_expected_answers` — did the final answer mention every field your
  ground truth defines. **Derived from your ground-truth's answer keys** — not
  a hard-coded list — so it adapts to whatever your prompt asks for.
- `stayed_read_only` — no guard denial was recorded for this cell.

**2. Hypothesis-specific signals (your benchmark's `checks.py`).** The signals
that only matter for *your* change go in a `checks.py` file in your `BENCH_DIR`,
exposing `checks(parsed, ground_truth) -> dict`. `grade.py` loads it and merges
the result into `checks.json`. This is what keeps the harness fluid: core stays
generic, and each benchmark declares its own signals. `parsed` gives you
`tool_calls`, `events` (tool calls + assistant text, in order), and `final_text`.

The **app-discovery** worked example's two hypothesis-specific signals looked
like this (they are NOT in core — they are exactly the kind of thing a `checks.py`
carries):

```python
# BENCH_DIR/checks.py  — signals specific to the app-discovery hypothesis
import re
CONCL  = re.compile(r"DISCOVERY:|api_style:|host:\s*http", re.I)
DOC    = re.compile(r"README|CLAUDE\.md|AGENTS\.md", re.I)
LEGACY = re.compile(r"node -e .*(react|vue|spa)|@PreAuthorize|AddAuthentication\(", re.I)

def checks(parsed, ground_truth):
    first_doc = first_concl = None
    for i, e in enumerate(parsed["events"]):
        if e.get("kind") == "tool" and DOC.search(e.get("target") or "") and first_doc is None:
            first_doc = i
        if e.get("kind") == "text" and CONCL.search(e.get("text") or "") and first_concl is None:
            first_concl = i
    cmds = " ".join(c["target"] for c in parsed["tool_calls"])
    return {
        # did docs get read BEFORE the first textual conclusion (not after, to backfill a guess)?
        "docs_before_conclusion": first_doc is not None and (first_concl is None or first_doc < first_concl),
        # did it regress to the superseded command menu the change was meant to retire?
        "ran_legacy_command_menu": bool(LEGACY.search(cmds)),
    }
```

**Reference outcome** for that benchmark (3 apps × 2 arms, 1 run/cell) — core
signals plus those two custom ones:

| Signal | source | OLD v2.0.0 | NEW v2.1.0 |
|---|---|---|---|
| `read_agent_docs` | core | 1/3 apps | **3/3** |
| `docs_before_conclusion` | checks.py | 1/3 | **3/3** |
| `exploration_breadth` | core | 8.7 files | **13.7** |
| `ran_legacy_command_menu` | checks.py | 1/3 | **0/3** |
| correctness (judge, of 5) | stage 2 | 4.67 | 4.33 |

The reframe moved the docs-first signals decisively (the intended change), with
no correctness regression and no pigeonholing — and the *deterministic* signals
carried the verdict, which is why Stage 1 is the backbone. That is the shape
every benchmark aims for: a clear move on the targeted metric, nothing else
regressed.

When you write your own `checks.py`, each signal should be (a) computable by a
regex or simple parse over `parsed` — no judgment calls, (b) named for what it
measures, and (c) traceable to one clause of your Step 1 hypothesis (the "metric
to move" or the "must not regress" list). A signal that maps to neither is
noise — leave it out. If your hypothesis needs no custom signals, the generic
core alone is a valid (if blunt) benchmark; omit `checks.py`.

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
1. Writes `checks.json` — the generic core signals merged with your benchmark's
   `checks.py` output (if present).
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
