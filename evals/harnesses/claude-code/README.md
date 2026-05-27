# Claude Code Eval Harness

Runs the StackHawk skill eval suite against Claude Code's non-interactive CLI (`claude -p`).

## Prerequisites

- **Claude Code CLI** installed and authenticated: `claude --version`
- **Python 3.11+**: `python3 --version`
- Run from the **agent-skills repo root** (plugin dirs are auto-detected)

## How it works

For each row in `evals/<skill>/prompts.csv`:

1. Runs `claude -p "<prompt>" --output-format stream-json --plugin-dir plugins/<skill>`
   in a fresh temp directory (isolated, no state leakage between runs)
2. Parses the JSONL event stream to extract bash commands, files written, and output text
3. Detects whether the skill triggered (skill-specific command patterns in the trace)
4. If the skill should have triggered and did: runs deterministic checks from
   `evals/<skill>/process-checks.json` against the captured trace
5. Saves `results/<skill>/<run-id>.jsonl` (raw trace) and `results/<skill>/<run-id>.result.json` (scored)

Optionally, `--rubric` runs a second `claude -p` call as a qualitative grader, using
`evals/<skill>/rubric-items.json` and enforcing `evals/rubric-schema.json` via `--json-schema`.

## Usage

```bash
# Run all prompts for a skill
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan
python3 evals/harnesses/claude-code/run-evals.py --skill api

# Run a single prompt by ID
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --id hw-07

# Dry run — print prompts without calling claude
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --dry-run

# Full-auto mode: agent can actually execute commands (--dangerously-skip-permissions)
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --full-auto

# Also run the qualitative rubric grader (extra cost + ~30s per run)
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --rubric

# Cap spend per run (default: $0.20)
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --max-budget 0.10
```

## Two modes

### Observe mode (default)

The agent runs normally but permissions are not bypassed. It will plan and narrate what
it would do — including bash commands it intends to execute — without necessarily
running them. Trigger detection and most process checks work because the agent names
the commands in its output even when execution is blocked.

**Use for:** trigger accuracy checks, output quality checks, rubric grading.

### Full-auto mode (`--full-auto`)

Passes `--dangerously-skip-permissions` so the agent can actually execute bash commands,
write files, and run `hawk` CLI calls. Results are more accurate for process checks that
require real execution (e.g. `hawk validate config` was actually run and passed).

**Use for:** end-to-end process verification when `hawk` CLI is installed and a target app
is available. Run in a trusted, isolated environment — not on a production machine.

## Understanding results

### Per-run result file (`results/<skill>/<run-id>.result.json`)

```json
{
  "platform": "claude-code",
  "skill": "hawkscan",
  "run_id": "hw-07",
  "should_trigger": true,
  "did_trigger": true,
  "trigger_correct": true,
  "bash_commands": ["hawk version", "hawkop app list", "hawk validate config stackhawk.yml", "hawk scan --json-output"],
  "files_written": ["stackhawk.yml"],
  "process_checks": [
    { "id": "preflight_version_check", "pass": true, "severity": "blocking", "signal_found": "hawk version" },
    { "id": "step2_no_local_yml_created", "pass": true, "severity": "blocking", "signal_found": null }
  ],
  "scoring": {
    "total": 22,
    "passed": 20,
    "blocking_failed": 1,
    "warning_failed": 1,
    "score": 80
  },
  "rubric_result": null,
  "cost_usd": 0.048
}
```

### Summary file (`results/<skill>/summary.json`)

Written after a full run. Tracks trigger accuracy, process score, false positives/negatives,
and per-run scores — useful for comparing skill versions over time.

### Scoring

| Check type | Deduction per failure |
|---|---|
| `blocking` | −15 points |
| `warning` | −5 points |

`overall_pass` in rubric results requires score ≥ 70 and zero blocking failures.

### Process checks only run when the skill should have triggered and did

If `should_trigger=false` and the skill correctly did not fire, no process checks run —
there is no workflow to grade. The run scores as a trigger-accuracy pass only.

## Raw traces

Each run saves the raw `claude --output-format stream-json` JSONL to
`results/<skill>/<run-id>.jsonl`. Open it to debug false negatives or unexpected behavior:

```bash
# See all bash commands the agent attempted
jq -r 'select(.type=="assistant") | .message.content[] | select(.type=="tool_use" and .name=="Bash") | .input.command' \
  results/hawkscan/hw-07.jsonl
```

## CI usage

The harness exits non-zero if trigger accuracy falls below 100% or any blocking check
fails. Wire it into CI after bumping a skill version to catch regressions:

```yaml
- name: Run skill evals
  run: |
    python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan
    python3 evals/harnesses/claude-code/run-evals.py --skill api
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Note: CI runs are in observe mode by default (no `--full-auto`), which avoids needing
a live `hawk` CLI or running application. Add `--full-auto` only in a dedicated sandbox.
