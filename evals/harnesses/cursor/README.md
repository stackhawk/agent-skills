# Cursor Eval Harness

Interactive manual harness for Cursor IDE. Results are saved in the standard
format for cross-platform comparison.

## Headless CLI — investigation needed

A `cursor-agent --headless` CLI has been reported but is unverified. If it
exists and supports `--output-format stream-json` and `CURSOR_API_KEY` auth,
this harness could be fully automated. Check `cursor --help` or the Cursor
docs and open a PR upgrading this to an automated harness if confirmed.

## Prerequisites

- Cursor IDE installed
- The agent-skills repo open in Cursor
- Cursor rules loaded from `cursor/.cursor/rules/` (generated .mdc files)

## Usage

```bash
python3 evals/harnesses/cursor/run-evals.py --skill hawkscan
python3 evals/harnesses/cursor/run-evals.py --skill api
python3 evals/harnesses/cursor/run-evals.py --skill hawkscan --id hw-07
python3 evals/harnesses/cursor/run-evals.py --skill hawkscan --rubric
```

## Workflow

1. The script prints each prompt and waits for you to run it in Cursor Agent chat
2. You record whether the skill triggered (y/n)
3. If it triggered correctly, you walk through the blocking process checks
4. Results are saved to `results/<skill>/` in the standard format

## Cursor rules

Skills for Cursor are the generated `.mdc` files in `cursor/.cursor/rules/`.
They are applied automatically when the repo is open. After editing any SKILL.md,
regenerate with:

```bash
bash scripts/generate-cursor-rules.sh
```
