# Agent Platform and Environment Detection

## Contents
- [HAWK_AGENT detection script](#hawk_agent-detection-script)
- [Environment variables set by this block](#environment-variables-set-by-this-block)

---

## HAWK_AGENT detection script

Run this block before every scan to export `COMMIT_SHA`, `BRANCH_NAME`, and `HAWK_AGENT`. These populate the `_STACKHAWK_AGENT`, `_STACKHAWK_GIT_COMMIT_SHA`, and `_STACKHAWK_GIT_BRANCH` tags in `stackhawk.yml`.

```bash
export COMMIT_SHA=$(git rev-parse HEAD)
export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

# Detect agent platform and model for _STACKHAWK_AGENT tag interpolation.
# Platform and model are detected independently — they can be from different vendors
# (e.g. Copilot IDE running an Anthropic model produces "copilot:claude-sonnet-4-6").
# Skip detection if HAWK_AGENT is already set (allows CI/CD override).
if [ -z "${HAWK_AGENT}" ]; then
  # Step 1: detect agent platform (the IDE / agentic tool)
  if [ -n "${CLAUDE_CODE}" ] || [ -d ".claude" ]; then
    _HAWK_PLATFORM=claude-code
  elif [ -n "${CURSOR_TRACE_ID}" ] || [ -d ".cursor" ]; then
    _HAWK_PLATFORM=cursor
  elif [ -f "GEMINI.md" ] || [ -n "${GEMINI_API_KEY}" ]; then
    _HAWK_PLATFORM=gemini
  elif [ -d ".codex" ]; then
    _HAWK_PLATFORM=codex
  elif [ -f ".github/copilot-instructions.md" ]; then
    _HAWK_PLATFORM=copilot
  else
    _HAWK_PLATFORM=unknown
  fi

  # Step 2: detect model from provider env vars (independent of platform)
  if [ -n "${ANTHROPIC_MODEL:-}" ]; then
    _HAWK_MODEL=${ANTHROPIC_MODEL}
  elif [ -n "${OPENAI_MODEL:-}" ]; then
    _HAWK_MODEL=${OPENAI_MODEL}
  elif [ -n "${GEMINI_MODEL:-}" ]; then
    _HAWK_MODEL=${GEMINI_MODEL}
  elif [ -n "${AZURE_OPENAI_DEPLOYMENT:-}" ]; then
    _HAWK_MODEL=${AZURE_OPENAI_DEPLOYMENT}
  else
    _HAWK_MODEL=
  fi

  export HAWK_AGENT="${_HAWK_PLATFORM}${_HAWK_MODEL:+:${_HAWK_MODEL}}"
  unset _HAWK_PLATFORM _HAWK_MODEL
fi

# Identify the driving skill for CLI usage telemetry (read by hawk/hawkop).
export _STACKHAWK_SKILL=hawkscan
```

## Environment variables set by this block

| Variable | Value | Used for |
|---|---|---|
| `COMMIT_SHA` | `git rev-parse HEAD` | `_STACKHAWK_GIT_COMMIT_SHA` tag |
| `BRANCH_NAME` | current branch name | `_STACKHAWK_GIT_BRANCH` tag |
| `HAWK_AGENT` | `<platform>:<model>` or `<platform>` | `_STACKHAWK_AGENT` tag |

`HAWK_AGENT` format examples:
- `claude-code:claude-sonnet-4-6` — Claude Code running Anthropic Sonnet
- `cursor:gpt-4o` — Cursor running OpenAI GPT-4o
- `copilot` — GitHub Copilot (model not detected)
- `unknown` — platform not detected

If `HAWK_AGENT` is already set (e.g. from CI/CD), the detection block skips — the pre-set value wins. This is the correct override path for CI pipelines that know their agent identity.
