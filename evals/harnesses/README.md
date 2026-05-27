# Eval Harnesses

Each harness connects the platform-agnostic test cases in `evals/` to a specific agent runtime.

## Platforms

| Platform | Type | Runner | Status |
|----------|------|--------|--------|
| **Claude Code** | Automated | `claude -p --output-format stream-json --verbose` | ✅ Multi-model |
| **Codex** | Automated | `codex exec --json --sandbox workspace-write` | ✅ Multi-model |
| **Cursor** | Automated | `agent -p --output-format stream-json --print` | ✅ Requires Pro |
| **Antigravity (agy)** | Automated | `agy -p --print` | ✅ Replaces Gemini |
| **Copilot** | Manual interactive | `run-evals.py` (records human observations) | ✅ No agentic CLI |

## Running locally

### Prerequisites

Install the CLI for whichever platform you want to test:

```bash
npm install -g @anthropic-ai/claude-code   # Claude Code
npm install -g @openai/codex               # Codex
npm install -g @google/gemini-cli          # Gemini
# Cursor agent CLI ships with the Cursor desktop app
# agy is an internal StackHawk tool
```

### Claude Code

```bash
# Requires: ANTHROPIC_API_KEY
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan
python3 evals/harnesses/claude-code/run-evals.py --skill api

# Override model (default: claude's configured default)
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --model claude-opus-4-7
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --model claude-haiku-4-5-20251001

# Single prompt
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --id hw-07

# Dry run (no API calls)
python3 evals/harnesses/claude-code/run-evals.py --skill hawkscan --dry-run
```

### Codex

One-time plugin setup:
```bash
codex plugin marketplace add .
codex plugin add hawkscan@stackhawk
codex plugin add api@stackhawk
```

```bash
# Requires: OPENAI_API_KEY
python3 evals/harnesses/codex/run-evals.py --skill hawkscan
python3 evals/harnesses/codex/run-evals.py --skill api

# Override model
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --model gpt-5.5
python3 evals/harnesses/codex/run-evals.py --skill hawkscan --model o3
```

### Cursor

```bash
# Requires: Cursor Pro account
python3 evals/harnesses/cursor/run-evals.py --skill hawkscan
python3 evals/harnesses/cursor/run-evals.py --skill api
```

### Antigravity (agy)

One-time plugin setup:
```bash
agy plugin install /path/to/agent-skills/plugins/hawkscan
agy plugin install /path/to/agent-skills/plugins/api
```

```bash
# Run with your main agy session idle (background tasks bleed in otherwise)
python3 evals/harnesses/agy/run-evals.py --skill hawkscan
python3 evals/harnesses/agy/run-evals.py --skill api

# Longer timeout for slow prompts
python3 evals/harnesses/agy/run-evals.py --skill hawkscan --print-timeout 300s
```

## How it works

For each row in `evals/<skill>/prompts.csv`, each harness:

1. Runs `agent -p "<prompt>"` in a fresh isolated directory
2. Captures bash commands executed and text output
3. Detects whether the skill triggered (via CLI command signals or skill-invocation text)
4. If triggered: scores against `evals/<skill>/process-checks.json` (deterministic)
5. Writes results to `evals/harnesses/<platform>/results/<skill>/`

## Trigger accuracy results (Claude Code baseline)

| Model | hawkscan | api |
|-------|---------|-----|
| Sonnet 4.6 | 100% | 100% |
| Opus 4.7   | 95%  | 100% |
| Haiku 4.5  | 85%  | 93%  |

## CI

The `.github/workflows/skill-evals.yml` workflow runs Claude Code + Codex + Gemini + Cursor on every PR that touches `plugins/` or `evals/`.

Required GitHub secrets:
- `ANTHROPIC_API_KEY` — Claude Code
- `OPENAI_API_KEY` — Codex
- `AGY_API_KEY` — Antigravity/agy
- `CURSOR_API_KEY` — Cursor (Pro required)

## Scoring

- **Trigger accuracy**: `did_trigger == should_trigger` → pass/fail per prompt
- **Process checks**: each check in `process-checks.json` scored against the captured trace
- **CI exits non-zero** if trigger accuracy < 100% or any blocking check fails
