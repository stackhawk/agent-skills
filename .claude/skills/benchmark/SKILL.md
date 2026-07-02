---
name: benchmark
version: 2.1.0
description: >
  Guides running a blind A/B benchmark that proves a change to agent-skills
  (skill or reference edits) actually moved the metric it was meant to move,
  without regressing correctness. Use when wrapping up a change to
  agent-skills (skill or reference edits) to prove it works via a blind A/B
  benchmark; invoked as /benchmark <description>. Do NOT trigger for customer
  scans or unrelated repos.
---

# Benchmark

This skill drives a two-arm (OLD vs NEW), three-repo, isolated-cell benchmark
that proves — or disproves — a hypothesis about a skill/reference change in
this repo. It is a maintainer tool for `stackhawk/agent-skills` itself, not a
customer-facing capability.

**Worked example:** the app-discovery reframe (skill v2.0.0 → v2.1.0) is used
as the running example throughout this skill — its process-checks, a sample
ground-truth file, and the reference outcome are written up in the **Grading**
reference (linked from Step 6). Model everything you author in Steps 5–6 on
that shape.

## Critical rules (apply throughout)

- **cwd = workdir.** The benchmarked agent always runs with its working
  directory set to the cloned target repo (`cell/workdir`), never this
  repo. It must never see `agent-skills` paths, ground truth, or the plan.
- **Guard denials come from the transcript, not memory.** `run.sh` greps
  `cell/transcript.jsonl` and `cell/agent.stderr` for `Denied (benchmark
  guard` into `cell/guard-denies.txt` — that file, not your recollection of
  what should have been blocked, is the source of truth for
  `stayed_read_only`.
- **Never auto-launch.** This skill is invoked explicitly as `/benchmark
  <description>`. The finishing-work nudge hook
  (`hooks/finishing-work-nudge.sh`) only ever *suggests* running it after a
  commit/PR/push touches skill material — it never runs the benchmark
  itself.
- **Isolation is per-cell.** Each `arm__app` cell gets its own clone, its own
  `CLAUDE_CONFIG_DIR`, and its own guard process. Nothing is shared across
  cells except the two materialized skill snapshots (`.skills/old`,
  `.skills/new`).

## Workflow

### Step 1 — Frame the hypothesis

From `<description>`, write down (even just mentally, but be explicit before
moving on):
- **What changed** — the exact skill/reference edit(s).
- **The problem it should solve** — the failure mode observed before the
  change.
- **The metric to move** — a concrete, observable signal (e.g. "reads repo
  docs before concluding", "close-rate on a known vuln class").
- **What must not regress** — correctness, safety, or behavior that the
  change should leave untouched.

If any of these four are still vague, ask the user before proceeding — a
benchmark built on a fuzzy hypothesis produces a fuzzy verdict.

### Step 2 — Resolve the two refs

Pick **OLD** (pre-change) and **NEW** (post-change) git refs in this repo:
- OLD: merge-base with `main`, the last release tag, or `HEAD~<n>` from
  before the change was made.
- NEW: the change itself — usually the working tree's branch HEAD, or a
  merged commit if the change already landed.

Also set `SKILL_SUBPATH` to the changed skill's path relative to the repo
root (e.g. `plugins/hawkscan/skills/hawkscan`) — this is what `run.sh`
passes to `git archive` to materialize each arm.

### Step 3 — Classify benchmark type + pick the guard profile

Decide whether the hypothesis is about **behavior during a task** (does the
agent explore/read/decide differently?) or about **whether a task gets
completed** (does the agent actually fix/build/close something?):

| Benchmark type | Guard profile | The agent may |
|---|---|---|
| Observational (behavior/process) | `readonly` | Read, grep, glob — no writes, no app starts, no scans |
| Task-completion (outcome) | `sandbox-rw` | Read + write, confined to `workdir`; run/build/scan locally |

This choice cascades into the grader (Step 6), the credentials needed (Step
7), and what the prompt must elicit. Full decision framework, worked
examples for both types, and the profile↔grader↔cred mapping:
→ [`references/designing-a-harness.md`](references/designing-a-harness.md)

### Step 4 — Token gate

Before doing any repo/prompt authoring work, verify the harness can actually
authenticate:

```bash
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || [ -n "$ANTHROPIC_API_KEY" ] || echo "MISSING"
```

If both are unset, **stop** and guide the user to set one up — do not
proceed to cloning repos or writing prompts on the assumption that
credentials will appear later.
→ [`references/token-setup.md`](references/token-setup.md)

### Step 5 — Pick 3 blind real repos

Choose 3 real, publicly cloneable repos relevant to the hypothesis. "Blind"
means: repos the harness clones fresh into each cell, not fixtures
handcrafted to flatter the change. Aim for variety (different languages,
frameworks, app shapes) so the result isn't an artifact of one codebase.
Verify each repo actually contains the material your hypothesis needs (e.g.
if testing auth-detection behavior, confirm the repo has real auth) before
committing to it.

Author `apps.tsv` — tab-separated, one row per app, no header:

```
<app>	<repo-url>	<pin>
```

`<pin>` is a tag/branch/sha `run.sh` passes to `git clone --branch`; it falls
back to an unpinned shallow clone if the pin doesn't resolve. Each row is
tab-separated — `<app-name>\t<repo-url>\t<pin>`, one per repo — using 3 real
repos pinned to release tags.

### Step 6 — Author the prompt, ground truth, and (observational) checks

Write `prompt.txt` — the single prompt given to the benchmarked agent in
every cell, both arms. It must exercise the exact capability the hypothesis
is about, and for observational benchmarks it must ask for a structured,
parseable conclusion — e.g. end the prompt with a literal `DISCOVERY:` block,
one line per answer field — so process-checks can be scored deterministically.

Write one `ground-truth/<app>.json` per repo — the author-judged correct
answers plus evidence citations, used by the grader.

For observational benchmarks, write the signals **specific to your hypothesis**
in `checks.py` (in `BENCH_DIR`), exposing `checks(parsed, ground_truth) -> dict`.
`grade.py` always computes a generic core (`read_agent_docs`,
`exploration_breadth`, `emitted_expected_answers`, `stayed_read_only`) and merges
your `checks.py` signals on top — so core stays fluid and each benchmark declares
what actually matters for its change. Omit `checks.py` if the core is enough.
Designing checks, ground truth, and the two graders (observational vs
task-completion):
→ [`references/grading.md`](references/grading.md)

### Step 7 — Run

Invoke `scripts/run.sh` with the config as environment variables:

| Env var | Meaning | Default |
|---|---|---|
| `OLD_REF` | git ref for the pre-change skill | *(required)* |
| `NEW_REF` | git ref for the post-change skill | `origin/main` |
| `SKILL_SUBPATH` | path to the skill within the repo | `plugins/hawkscan/skills/hawkscan` |
| `BENCH_DIR` | dir holding `apps.tsv`, `prompt.txt`, `ground-truth/` (+ optional `checks.py`) | *(required)* |
| `PROFILE` | guard profile: `readonly` or `sandbox-rw` | `readonly` |
| `GRADER` | `observational` or `task-completion` | `observational` |
| `MODEL` | model the benchmarked agent runs as | `claude-sonnet-5` |
| `JUDGE_MODEL` | model used for the skill-blind judge | `claude-opus-4-8` |
| `CRED_ENV` | space-separated env var names to pass through into each cell (e.g. `HAWK_API_KEY`) | *(empty)* |

Example invocation — point `BENCH_DIR` at the directory holding the
`apps.tsv`, `prompt.txt`, and `ground-truth/` you authored in Steps 5–6:

```bash
cd .claude/skills/benchmark
OLD_REF=<old-sha-or-tag> NEW_REF=<new-sha-or-branch> \
SKILL_SUBPATH=plugins/hawkscan/skills/hawkscan \
BENCH_DIR="$(pwd)/my-benchmark" \
PROFILE=readonly GRADER=observational \
scripts/run.sh
```

Sanity-check the plan first with `scripts/run.sh --dry-run` — it prints
every `arm__app` cell it would create (materializing nothing, cloning
nothing) so you can catch a bad `apps.tsv` or ref before spending real agent
runs. Drop `--dry-run` to execute for real; this clones each repo fresh into
`$BENCH_DIR/runs/<timestamp>/cells/<arm>__<app>/workdir`, runs the agent
headless with the guard wired in, grades each cell, and writes
`$BENCH_DIR/runs/<timestamp>/report.md`.

### Step 8 — Report the honest verdict

Read `report.md` and state plainly:
- Did the target metric actually move in the direction the hypothesis
  predicted?
- Did correctness/safety hold (no regression on the "must not regress"
  list from Step 1)?
- The **n=3 repos, 1 run per cell** limitation — this is directional
  evidence, not a statistically significant result. Say so explicitly;
  don't oversell a single run.
- If the metric didn't move either way, that is still a valid, reportable
  result — see the "non-discriminating signals are still results" rule in
  → [`references/methodology.md`](references/methodology.md)

Before concluding, skim → [`references/gotchas.md`](references/gotchas.md)
for the durable lessons that have bitten this harness before (isolation
leaks, guard-capture mistakes, headless flags, per-cell state, honest
reporting of flat results).
