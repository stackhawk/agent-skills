# Agent Platform and Environment Detection

## Contents
- [HAWK_AGENT detection script](#hawk_agent-detection-script)
- [Environment variables set by this block](#environment-variables-set-by-this-block)

---

## HAWK_AGENT detection script

Run this block before every scan to export `COMMIT_SHA`, `BRANCH_NAME`, and `HAWK_AGENT`. These
populate the `_STACKHAWK_AGENT`, `_STACKHAWK_GIT_COMMIT_SHA`, and `_STACKHAWK_GIT_BRANCH` tags in
`stackhawk.yml`. `HAWK_AGENT` is also exported as `_STACKHAWK_AGENT` — a second delivery channel
alongside the yml tag, read directly by the CLI's own detection precedence. The yml tag's
`${HAWK_AGENT:none}` default is a sentinel: when this block didn't run (or ran before
`HAWK_AGENT` was populated), hawk fills the blank/`none` value from its own built-in detection
when an agent is identified; if no agent is detected, the `none` default stands.

> **WARNING:** Run this block verbatim — do not retype or paraphrase the `export` lines. A
> session was observed hand-writing a malformed value (`claude-code/claude-opus-4-8` instead of
> the contract's `claude-code:claude-opus-4-8`), which broke detection entirely. The block below,
> not memory, is the source of truth.

```bash
export COMMIT_SHA=$(git rev-parse HEAD)
export BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

# Detect agent platform and model for _STACKHAWK_AGENT tag interpolation.
# Platform and model are detected independently — they can be from different vendors
# (e.g. Copilot IDE running an Anthropic model produces "copilot:claude-sonnet-4-6").
# Skip detection if HAWK_AGENT or _STACKHAWK_AGENT is already set (allows CI/CD override).
if [ -z "${HAWK_AGENT}" ] && [ -z "${_STACKHAWK_AGENT}" ]; then
  # Step 1: detect agent platform (the IDE / agentic tool). The env markers mirror
  # hawk's own agent registry (CLAUDECODE=1, CODEX_THREAD_ID, GEMINI_CLI=1, OPENCODE,
  # CURSOR_TRACE_ID). A nested launch — e.g. Codex started from inside a Claude Code
  # session — inherits the outer host's markers too, so when more than one fires the
  # platform is left as the `none` sentinel and hawk's process-ancestry detection
  # picks the innermost host. Directory markers are the fallback when no env fires.
  _HAWK_HOSTS=0
  if [ "${CLAUDECODE:-}" = "1" ]; then _HAWK_PLATFORM=claude-code; _HAWK_HOSTS=$((_HAWK_HOSTS + 1)); fi
  if [ -n "${CODEX_THREAD_ID:-}" ]; then _HAWK_PLATFORM=codex; _HAWK_HOSTS=$((_HAWK_HOSTS + 1)); fi
  if [ "${GEMINI_CLI:-}" = "1" ]; then _HAWK_PLATFORM=gemini; _HAWK_HOSTS=$((_HAWK_HOSTS + 1)); fi
  if [ -n "${OPENCODE:-}" ]; then _HAWK_PLATFORM=opencode; _HAWK_HOSTS=$((_HAWK_HOSTS + 1)); fi
  if [ -n "${CURSOR_TRACE_ID:-}" ]; then _HAWK_PLATFORM=cursor; _HAWK_HOSTS=$((_HAWK_HOSTS + 1)); fi
  if [ "${_HAWK_HOSTS}" -gt 1 ]; then
    _HAWK_PLATFORM=none
  elif [ "${_HAWK_HOSTS}" -eq 0 ]; then
    if [ -d ".claude" ]; then
      _HAWK_PLATFORM=claude-code
    elif [ -d ".cursor" ]; then
      _HAWK_PLATFORM=cursor
    elif [ -f "GEMINI.md" ] || [ -n "${GEMINI_API_KEY:-}" ]; then
      _HAWK_PLATFORM=gemini
    elif [ -d ".codex" ]; then
      _HAWK_PLATFORM=codex
    elif [ -f ".github/copilot-instructions.md" ]; then
      _HAWK_PLATFORM=copilot
    else
      _HAWK_PLATFORM=none
    fi
  fi
  unset _HAWK_HOSTS

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

  # `none` is a sentinel on both sides of the contract: hawk treats it as "no answer"
  # and fills the platform from its own detection, so never attach a model to it.
  if [ "${_HAWK_PLATFORM}" = "none" ]; then
    export HAWK_AGENT=none
  else
    export HAWK_AGENT="${_HAWK_PLATFORM}${_HAWK_MODEL:+:${_HAWK_MODEL}}"
  fi
  unset _HAWK_PLATFORM _HAWK_MODEL
fi

# Also deliver the detected value via env — a second channel alongside the yml tag. The
# CLI's own precedence rules take over from here (explicit env wins; absence falls through
# to the CLI's built-in detection rather than a literal "none"). A pre-set _STACKHAWK_AGENT
# (e.g. from CI/CD) is never clobbered; the if-form stays safe under `set -e`.
if [ -z "${_STACKHAWK_AGENT}" ]; then
  export _STACKHAWK_AGENT="${HAWK_AGENT}"
fi

# Identify the driving skill for CLI usage telemetry (read by hawk/hawkop).
export _STACKHAWK_SKILL=hawkscan
```

## Environment variables set by this block

| Variable | Value | Used for |
|---|---|---|
| `COMMIT_SHA` | `git rev-parse HEAD` | `_STACKHAWK_GIT_COMMIT_SHA` tag |
| `BRANCH_NAME` | current branch name | `_STACKHAWK_GIT_BRANCH` tag |
| `HAWK_AGENT` | `<platform>:<model>` or `<platform>` | `_STACKHAWK_AGENT` tag in `stackhawk.yml` |
| `_STACKHAWK_AGENT` | copy of `HAWK_AGENT` | Second channel — read directly by the CLI's agent-detection precedence |

`HAWK_AGENT` format examples:
- `claude-code:claude-sonnet-4-6` — Claude Code running Anthropic Sonnet
- `cursor:gpt-4o` — Cursor running OpenAI GPT-4o
- `copilot` — GitHub Copilot (model not detected)
- `none` — platform not detected, or more than one host marker fired (a nested launch such
  as Codex started from inside Claude Code). hawk fills the platform from its own
  process-ancestry detection; it never records a literal `none` when an agent is found.

If `HAWK_AGENT` (or `_STACKHAWK_AGENT`) is already set (e.g. from CI/CD), the detection block
skips — the pre-set value wins: a pre-set `HAWK_AGENT` is copied into `_STACKHAWK_AGENT`, and a
pre-set `_STACKHAWK_AGENT` is never clobbered. This is the correct override path for CI
pipelines that know their agent identity.
