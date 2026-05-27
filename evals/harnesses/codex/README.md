# Codex Eval Harness

Automated harness using `codex exec --json --full-auto`. Mirrors the Claude Code harness.

## Prerequisites

- Codex CLI installed and authenticated
- Python 3.11+
- Run from the agent-skills repo root

## How it works

1. For each prompt, runs `codex exec --json --full-auto "<prompt>"` in a fresh temp dir
2. Copies the skill's SKILL.md + references into `.codex/skills/<skill>/` in the temp dir for discovery
3. Parses the JSONL event stream (`item.started` / `item.completed` / `turn.completed`) to extract commands and output
4. Scans the temp dir for files created during the run
5. Detects trigger, runs process checks, writes scored results

Rubric grading uses `codex exec "<prompt>" --output-schema <schema> -o <output_file>`.

## Usage

```bash
python3 evals/harnesses/codex/run-evals.py --skill hawkscan
python3 evals/harnesses/codex/run-evals.py --skill api
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --id hw-07
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --dry-run
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --rubric
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --no-full-auto  # sandbox mode
```

## Inspecting a trace

```bash
# All commands the agent ran
jq -r 'select(.type=="item.started") | select(.item.type=="command_execution") | .item.command' \
  results/hawkscan/hw-07.jsonl

# Token usage per turn
jq 'select(.type=="turn.completed") | .usage' results/hawkscan/hw-07.jsonl
```
