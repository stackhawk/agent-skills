# Eval Harnesses

Each harness connects the platform-agnostic test cases in `evals/` to a specific agent runtime.

## Platforms

| Platform | Type | Runner | Status |
|----------|------|--------|--------|
| **Claude Code** | Automated | `claude -p --output-format stream-json --verbose` | ✅ Multi-model |
| **Codex** | Automated | `codex exec --json --sandbox workspace-write` | ✅ Multi-model |
| **Cursor** | Automated | `agent -p --output-format stream-json --print` | ✅ Requires Pro |
| **Antigravity (agy)** | Automated | `agy -p --print` | ✅ Replaces Gemini |
| **Copilot** | Automated | `copilot -p --output-format json --allow-all-tools` | ✅ Unambiguous trigger detection |

## Running locally

### Prerequisites

Install [uv](https://docs.astral.sh/uv/) if you don't have it — `uv run` handles dependency installation automatically, so no separate `uv sync` step is needed before running evals.

Install the CLI for whichever platform you want to test:

```bash
npm install -g @anthropic-ai/claude-code   # Claude Code
npm install -g @openai/codex               # Codex
curl https://cursor.com/install -fsS | bash # Cursor
curl -fsSL https://antigravity.google/install-cli | bash  # Antigravity (agy)
# Cursor agent CLI ships with the Cursor desktop app
```

### Claude Code

```bash
# Requires: ANTHROPIC_API_KEY
uv run evals --harness claude-code --skill hawkscan
uv run evals --harness claude-code --skill api

# Override model (default: claude's configured default)
uv run evals --harness claude-code --skill hawkscan --model claude-opus-4-7
uv run evals --harness claude-code --skill hawkscan --model claude-haiku-4-5-20251001

# Single prompt
uv run evals --harness claude-code --skill hawkscan --id hw-07

# Dry run (no API calls)
uv run evals --harness claude-code --skill hawkscan --dry-run
```

### Codex

One-time plugin setup:
```bash
codex plugin marketplace add .
codex plugin add hawkscan@stackhawk
codex plugin add stackhawk-api@stackhawk
```

```bash
# Requires: OPENAI_API_KEY
uv run evals --harness codex --skill hawkscan
uv run evals --harness codex --skill api

# Override model
uv run evals --harness codex --skill hawkscan --model gpt-5.5
uv run evals --harness codex --skill hawkscan --model o3
```

### Cursor

```bash
# Requires: Cursor Pro account
uv run evals --harness cursor --skill hawkscan
uv run evals --harness cursor --skill api
```

### Copilot

```bash
# Requires: GitHub Copilot account (gh copilot or copilot CLI)
# No plugin setup needed — loads directly via --plugin-dir
uv run evals --harness copilot --skill hawkscan
uv run evals --harness copilot --skill api
uv run evals --harness copilot --skill hawkscan --model gpt-5.3-codex
```

> **Best trigger detection**: Copilot emits an explicit `skill` tool call
> (`tool.execution_start {toolName:"skill", arguments:{skill:"hawkscan"}}`)
> when a skill fires — no heuristic signal-matching required.

### Antigravity (agy)

One-time plugin setup:
```bash
agy plugin install /path/to/agent-skills/plugins/hawkscan
agy plugin install /path/to/agent-skills/plugins/api
```

```bash
# Run with your main agy session idle (background tasks bleed in otherwise)
uv run evals --harness agy --skill hawkscan
uv run evals --harness agy --skill api

# Longer timeout for slow prompts
uv run evals --harness agy --skill hawkscan --print-timeout 300s
```

> **Shims vs adapters**: The per-platform `run-evals.py` scripts are back-compat
> shims that forward to `uv run evals`. Full stream-parsing adapter logic lives in
> `evals/harnesses/<platform>/adapter.py`; **claude-code, codex, cursor, and agy**
> all have real `adapter.py` implementations. Copilot and Gemini use the legacy
> shim path (Gemini is frozen). The per-platform `run-evals.py` files remain thin
> forwarding shims for back-compat.

## How it works

For each entry in `evals/<skill>/prompts.yaml`, each harness:

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

The `.github/workflows/skill-evals.yml` workflow is tiered:

- **Every PR + push**: runs `uv run validate` (no API keys required), then runs
  **all four platforms** (claude-code, codex, agy, cursor). On PRs, claude-code
  uses the Haiku model to stay within budget; the other platforms run their
  default model.
- **Merge to main + manual dispatch**: runs the full multi-model matrix across
  all platforms.
- **PR comment job**: collects `cell.json` artifacts from all platform jobs,
  fetches the released-tag baseline (best-effort), and posts a consolidated
  digest comment via `uv run report --pr`.

Required GitHub secrets:
- `ANTHROPIC_API_KEY` — Claude Code
- `OPENAI_API_KEY` — Codex
- `AGY_API_KEY` — Antigravity/agy
- `CURSOR_API_KEY` — Cursor (Pro required)

## Scoring

- **Trigger accuracy**: `did_trigger == should_trigger` → pass/fail per prompt
- **Process checks**: each check in `process-checks.json` scored against the captured trace
- **CI exits non-zero** if trigger accuracy < 100% or any blocking check fails
