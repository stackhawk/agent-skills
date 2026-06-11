# Claude Code Eval Harness

Runs the StackHawk skill eval suite against Claude Code's non-interactive CLI (`claude -p`).

## Prerequisites

- **Claude Code CLI** installed and authenticated: `claude --version`
- **Python 3.11+** with `uv`: `uv run evals --help`
- Run from the **agent-skills repo root** (plugin dirs are auto-detected)

## Invocation

```bash
# Run all prompts for a skill (preferred)
uv run evals --harness claude-code --skill hawkscan
uv run evals --harness claude-code --skill api

# Run a specific model
uv run evals --harness claude-code --skill hawkscan --model claude-haiku-4-5-20251001

# Cap spend per run (default: $0.20)
uv run evals --harness claude-code --skill hawkscan --max-budget 0.10

# Full-auto mode: agent executes commands (--dangerously-skip-permissions)
uv run evals --harness claude-code --skill hawkscan --full-auto

# Suppress progress UI (used in CI)
uv run evals --harness claude-code --skill hawkscan --bare
```

`run-evals.py` in this directory is a back-compat shim that forwards to `uv run evals --harness claude-code`. Use the `uv run evals` form going forward.

## Config source

Prompts and trigger labels are loaded from `evals/<skill>/prompts.yaml` (not prompts.csv — the CSV was removed during the YAML migration). Process checks come from `evals/<skill>/process-checks.json`.

## How it works

For each prompt in `evals/<skill>/prompts.yaml`:

1. `ClaudeCodeAdapter.launch()` runs `claude -p "<prompt>" --output-format stream-json --plugin-dir plugins/<skill>` in a fresh temp directory (isolated, no state leakage between runs). The raw stdout is parsed in-memory; no raw `.jsonl` file is persisted.
2. `parse_stream()` extracts bash commands, files written/edited, output text, and cost from the JSONL event stream.
3. `detect_trigger()` checks whether the skill triggered using CLI command signals (e.g. `hawk scan`) and invocation-phrase signals in the output text.
4. If the skill should have triggered and did, process checks from `process-checks.json` are run against the captured trace.
5. A verdict (`pass`, `pass-slow`, or `fail`) is assigned and an `EvalResult` is written to `results/<skill>/<run-id>.result.json`.

## Two modes

### Observe mode (default)

Permissions are not bypassed. The agent plans and narrates what it would do — including bash commands it intends to run — without necessarily executing them. Trigger detection and most process checks still work because the agent names the commands in its output.

**Use for:** trigger accuracy checks, output quality checks, CI.

### Full-auto mode (`--full-auto`)

Passes `--dangerously-skip-permissions` so the agent can actually execute bash commands, write files, and run `hawk` CLI calls. Results are more accurate for process checks that require real execution.

**Use for:** end-to-end process verification when `hawk` CLI is installed and a target app is available. Run in a trusted, isolated environment.

## Understanding results

### Per-run result file (`results/<skill>/<run-id>.result.json`)

Conforms to the `EvalResult` Pydantic model (`evals/lib/models.py`):

```json
{
  "platform": "claude-code",
  "skill": "hawkscan",
  "run_id": "hw-07",
  "should_trigger": true,
  "did_trigger": true,
  "trigger_correct": true,
  "verdict": "pass",
  "budget_breaches": [],
  "process_checks": [
    { "id": "preflight_version_check", "passed": true, "severity": "blocking", "signal_found": "hawk version", "anti_found": null },
    { "id": "step2_no_local_yml_created", "passed": true, "severity": "blocking", "signal_found": null, "anti_found": null }
  ],
  "score": 100,
  "cost_usd": 0.048
}
```

### Summary file (`results/<skill>/summary.json`)

Written after a full run. Tracks trigger accuracy, process score, false positives/negatives, and per-run scores.

### Scoring

| Check type  | Deduction per failure |
|---|---|
| `blocking`  | −15 points |
| `warning`   | −5 points |

Verdict is `pass` if trigger is correct and score ≥ 70 with zero blocking failures; `pass-slow` if correct but over budget; `fail` otherwise.

### Process checks only run when the skill should have triggered and did

If `should_trigger=false` and the skill correctly did not fire, no process checks run — there is no workflow to grade.

## adapter.py

`ClaudeCodeAdapter` (`adapter.py`) implements the `HarnessAdapter` protocol for this platform:

- `parse_stream(raw)` — parses `claude --output-format stream-json` JSONL into a `ParsedRun`
- `detect_trigger(run, skill)` — checks CLI command signals and invocation-phrase signals
- `launch(prompt, skill, run_id, ...)` — spawns `claude -p` in a temp directory, captures stdout in-memory, and returns a `ParsedRun`

## CI usage

```yaml
- name: Run skill evals
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: |
    uv run evals --harness claude-code --skill hawkscan --bare --max-budget 0.15
    uv run evals --harness claude-code --skill api --bare --max-budget 0.15
```

CI runs use observe mode by default (no `--full-auto`), which avoids needing a live `hawk` CLI or running application.
