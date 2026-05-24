# Eval Harnesses

A harness connects the platform-agnostic test cases in `evals/` to a specific agent runtime. Each harness:

1. Runs each prompt from the skill's `prompts.csv`
2. Captures what the agent did (trace, commands, output, generated files)
3. Scores the captured run against `process-checks.json` (deterministic)
4. Optionally runs a rubric grader against `rubric-items.json` + `rubric-schema.json` (qualitative)
5. Writes a results file for comparison across versions

## Harnesses

| Platform | Type | Runner | Status |
|----------|------|--------|--------|
| Claude Code | Automated | `claude -p --output-format stream-json` | ✅ Done |
| Codex | Automated | `codex exec --json --full-auto` | ✅ Done |
| Copilot | Manual interactive | `run-evals.py` (records human observations) | ✅ Done |
| Cursor | Manual interactive | `run-evals.py` (records human observations) | ✅ Done |
| Gemini CLI | — | `gemini --prompt` | Planned |

**Copilot**: No agentic CLI exists — `gh copilot` supports only suggest/explain.
**Cursor**: A headless CLI (`cursor-agent --headless`) has been reported but is unverified — see `cursor/README.md`.

## Harness contract

Each harness must produce a results file at `evals/harnesses/<platform>/results/<skill>/<run-id>.json` with this shape:

```json
{
  "platform": "codex",
  "skill": "hawkscan",
  "run_id": "hw-07",
  "prompt": "...",
  "should_trigger": true,
  "did_trigger": true,
  "process_checks": [
    { "id": "preflight_version_check", "pass": true, "signal_found": "hawk version" }
  ],
  "rubric_result": null
}
```

`rubric_result` is null until a qualitative grader pass is run. It should be filled with the output conforming to `../rubric-schema.json`.

## Scoring

- **Trigger accuracy**: `did_trigger == should_trigger` → pass/fail per row
- **Process checks**: each check in `process-checks.json` → pass/fail + signal found
- **Rubric score**: 0–100 from the qualitative grader (optional, slower)

## Adding a new harness

1. Create `evals/harnesses/<platform>/run-evals.sh` (or `.mjs`, `.py`)
2. For each row in `evals/<skill>/prompts.csv`:
   - Run the agent with the prompt
   - Capture commands executed and output
3. For each check in `evals/<skill>/process-checks.json`:
   - Search the captured trace for `signals` → pass
   - Search for `anti_patterns` → fail if found
4. Write results to the contract format above
5. Optionally run a grader agent with `evals/<skill>/rubric-items.json` grader_prompt and enforce `rubric-schema.json` output
