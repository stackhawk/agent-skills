# Skill Evals

Evaluation assets for the `hawkscan`, `api`, and `stackhawk-data-seed` skills. The structure follows the pattern: **prompt → captured run → deterministic checks + rubric score → comparable number over time.**

## Structure

```
evals/
  hawkscan/
    prompts.csv          # 20 trigger/no-trigger test cases for the hawkscan skill
    process-checks.json  # Deterministic checks: commands, files, and patterns that must (or must not) appear
    rubric-items.json    # Qualitative rubric check definitions for style and correctness grading
  api/
    prompts.csv          # 16 trigger/no-trigger test cases for the api skill
    process-checks.json  # Deterministic checks
    rubric-items.json    # Qualitative rubric check definitions
  stackhawk-data-seed/
    prompts.csv          # Trigger/no-trigger cases for the stackhawk-data-seed skill
    process-checks.json  # Deterministic checks for discovery, dialog, artifact emission, and contract boundaries
    rubric-items.json    # Qualitative rubric check definitions
  rubric-schema.json     # Shared JSON Schema — constrains rubric grader output format
  harnesses/
    README.md            # How to build platform-specific harnesses (Codex, Claude, Gemini, etc.)
```

## Three layers of evaluation

### 1. Trigger evals (`prompts.csv`)

Each row is a prompt with a `should_trigger` flag. Run the prompt through an agent and record whether the skill was invoked.

Columns: `id`, `should_trigger`, `invocation_type`, `prompt`, `notes`

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

Harnesses are platform-specific. See `harnesses/README.md` for the contract and planned implementations.

**Manual checklist:**
1. Run the prompt in the target agent
2. Check the output and any generated files against `process-checks.json` — look for `signals` (must appear) and `anti_patterns` (must not appear)
3. Run a grader with the `grader_prompt` from `rubric-items.json` against the output; require JSON output conforming to `rubric-schema.json`
4. Record results per check; track scores over time to detect regressions

## Adding test cases

When a skill bug or regression is discovered:

1. Add a new row to the relevant `prompts.csv` capturing the prompt that exposed the bug
2. If the bug was a missing process step, add a check to `process-checks.json`
3. If the bug was a style or qualitative issue, add a check to the relevant `rubric-items.json`

This keeps the eval set growing as a living record of every failure mode the skill has encountered.
