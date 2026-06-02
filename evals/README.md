# Skill Evals

Evaluation assets for the `hawkscan`, `api`, and `stackhawk-data-seed` skills. The structure follows the pattern: **prompt → captured run → deterministic checks + rubric score → comparable number over time.**

## Structure

```
evals/
  hawkscan/
    prompts.yaml         # 20 trigger/no-trigger test cases for the hawkscan skill
    process-checks.json  # Deterministic checks: commands, files, and patterns that must (or must not) appear
    rubric-items.json    # Qualitative rubric check definitions for style and correctness grading
  api/
    prompts.yaml         # 16 trigger/no-trigger test cases for the api skill
    process-checks.json  # Deterministic checks
    rubric-items.json    # Qualitative rubric check definitions
  stackhawk-data-seed/
    prompts.csv          # Trigger/no-trigger cases for the stackhawk-data-seed skill
    process-checks.json  # Deterministic checks for discovery, dialog, artifact emission, and contract boundaries
    rubric-items.json    # Qualitative rubric check definitions
  rubric-schema.json     # Shared JSON Schema — constrains rubric grader output format
  lib/                   # Shared library: models, config, grading, harness, replay, compare, reporting
  cli.py                 # Unified CLI entrypoints (evals, compare, regrade, validate)
  harnesses/
    README.md            # How to build platform-specific harnesses (Codex, Claude, etc.)
```

## Three layers of evaluation

### 1. Trigger evals (`prompts.yaml`)

Each entry is a prompt with a `should_trigger` flag. Run the prompt through an agent and record whether the skill was invoked. Each prompt may also set a `budget` (cost_usd / bash_commands / output_tokens / wall_seconds) and an `expected` list (each item has exactly one of: signal / anti_pattern / check_id).

Fields: `id`, `should_trigger`, `invocation_type`, `prompt`, `notes`

Invocation types:
- `explicit` — skill named directly (e.g. `$hawkscan` or `$api`)
- `implicit` — prompt matches the skill's description keywords without naming it
- `contextual` — realistic noisy prompt that should trigger based on context
- `negative` — should NOT trigger; tests false-positive prevention

### 2. Process evals (`process-checks.json`)

For runs where the skill triggered, verify that specific commands were executed, files were created correctly, and known anti-patterns were avoided. Every check has a `severity`:

- `blocking` — must pass; a failure here means the skill produced incorrect or risky behavior
- `warning` — should pass; a failure here indicates a quality gap but not a hard error

### 3. Rubric evals (`rubric-items.json` + `rubric-schema.json`)

A second, read-only grader pass over the agent's output and generated files. The grader evaluates style, conventions, and qualitative correctness against the items in `rubric-items.json`, then returns JSON conforming to `rubric-schema.json`. This catches issues that deterministic checks can't, like incorrect YAML structure, missing announcements, or wrong phase ordering.

## Running evals

This is a uv project. All commands go through `uv run`.

| Task | Command |
|---|---|
| Validate config (no keys) | `uv run validate` |
| Run a skill | `uv run evals --harness claude-code --skill hawkscan` |
| Single prompt | `uv run evals --harness claude-code --skill hawkscan --id hw-07` |
| Compare with/without skill | `uv run compare --harness claude-code --skill hawkscan` |
| Regrade a saved trace (free) | `uv run regrade <trace.jsonl> --skill hawkscan` |

Per-prompt config lives in `evals/<skill>/prompts.yaml`. Each prompt may set a
`budget` (cost_usd / bash_commands / output_tokens / wall_seconds) and an
`expected` list (each item has exactly one of: signal / anti_pattern / check_id).
A correct run that breaches a budget grades as PASS-SLOW. A process-check in
`process-checks.json` may carry `applies_to: [<prompt id>]` to scope it to
specific prompts (absent = applies to all).

See `harnesses/README.md` for per-platform instructions and CI setup.

### Reports

**Per-job summaries.** Each `uv run evals` run writes a JUnit-style table to
`$GITHUB_STEP_SUMMARY`: one row per test, failures-first ordering,
`✅ PASS / ◆ PASS-SLOW / ❌ FAIL` verdicts. It also writes a `cell.json`
artifact in the results directory so downstream steps can aggregate across
jobs.

**PR digest comment.** When a PR lands, the `comment` CI job collects all
`cell.json` artifacts and runs:

```
uv run report --pr [--results-dir DIR] [--baseline-dir DIR] [--lift-dir DIR] [--out FILE]
```

This produces a consolidated Markdown digest posted as a sticky PR comment.
The digest contains:

- **Matrix overview** — one row per (platform × skill × model) cell showing
  trigger accuracy, ✅/◆/❌ verdict mix, and aggregate score.
- **Per-cell tables** — the same failures-first rows from each job summary.
- **Regression vs released-tag baseline** — the `comment` job fetches the
  baseline from the most recent release's `capture-baseline.yml` run
  (best-effort; missing baseline degrades gracefully to "no baseline
  available"). Comparison is pure deterministic threshold math: per-test
  verdict-flips (fixed / regressed) and aggregate score deltas with a ±3
  band → better / worse / no-change. No AI or LLM calls are used.
- **Skill lift section** — with-skill vs without-skill verdict comparison
  showing how many prompts move from FAIL→PASS when the skill is active.

Baselines are captured at release tags by `capture-baseline.yml`, which is
triggered automatically from `release.yml`.

## Adding test cases

When a skill bug or regression is discovered:

1. Add a new entry to the relevant `prompts.yaml` capturing the prompt that exposed the bug
2. If the bug was a missing process step, add a check to `process-checks.json`
3. If the bug was a style or qualitative issue, add a check to the relevant `rubric-items.json`

This keeps the eval set growing as a living record of every failure mode the skill has encountered.
