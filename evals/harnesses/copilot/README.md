# Copilot Eval Harness

Interactive manual harness for GitHub Copilot. There is no agentic task
execution CLI for Copilot — `gh copilot` supports only `suggest` and `explain`.
This harness walks you through each prompt interactively so you can record
what Copilot did and produce results in the standard format.

## Prerequisites

- VS Code with GitHub Copilot extension (agent mode enabled)
- The agent-skills repo open in VS Code
- Skills discoverable via `skills/` symlinks at the repo root

## Usage

```bash
python3 evals/harnesses/copilot/run-evals.py --skill hawkscan
python3 evals/harnesses/copilot/run-evals.py --skill api
python3 evals/harnesses/copilot/run-evals.py --skill hawkscan --id hw-07
python3 evals/harnesses/copilot/run-evals.py --skill hawkscan --rubric
```

## Workflow

1. The script prints each prompt and waits for you to run it in Copilot Chat (agent mode)
2. You record whether the skill triggered (y/n)
3. If it triggered correctly, you walk through the blocking process checks
4. Results are saved to `results/<skill>/` in the standard format

Results can be compared directly against Claude Code and Codex runs since
they share the same output schema.
