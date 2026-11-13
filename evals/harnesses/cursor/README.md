# Cursor Eval Harness

Runs the eval prompts against the Cursor CLI in headless mode
(`-p --output-format stream-json`) and saves results in the standard format for
cross-platform comparison. The adapter launches `cursor-agent`, and falls back to
`agent` only when `cursor-agent` is not on PATH: another tool's CLI can also be
named `agent`.

## Prerequisites

- The Cursor CLI: `curl https://cursor.com/install -fsS | bash`
- `CURSOR_API_KEY` in the environment (never on the command line), or a CLI that
  can run headless prompts with its login

## Usage

```bash
uv run evals --harness cursor --skill hawkscan
uv run evals --harness cursor --skill api
uv run evals --harness cursor --skill hawkscan --id hw-07
uv run evals --harness cursor --skill hawkscan --rubric
```

`python3 evals/harnesses/cursor/run-evals.py --skill <skill>` forwards to the same CLI.

## What each run installs

When the skill is loaded, each run gets a fresh workspace with the layout users
install: `scripts/install.sh --platform cursor` writes the five skills to
`.cursor/skills/`, the router and `stackhawk.yml` pointer rules to `.cursor/rules/`,
and the stop hook. The stop hook stays silent during a run: the Cursor CLI runs
stop hooks only in interactive sessions, not with `-p`, and the workspace is not a git
repository. The matrix therefore measures the skills and rules, not the hook.

The published Cursor baseline was measured with the deprecated generated rules
(`cursor/.cursor/rules/`) only: no skills and no hook. Run the Cursor matrix again
before you compare a new result with that baseline.
