"""The hawkscan hooks must record Claude Code's real session id, and the skill's
detection block must recognise each agent by the variables it actually sets.

Claude Code sets `CLAUDECODE=1` and `CLAUDE_CODE_SESSION_ID` and passes `session_id` in
every hook's stdin payload; it never sets `CLAUDE_CODE` or `CLAUDE_SESSION_ID`
(https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/hooks). The
hooks once read `CLAUDE_SESSION_ID`, so every session record had an empty
`hostSessionId`, and the detection block tested `CLAUDE_CODE`, so Claude Code was found
only through a `.claude/` directory.

Each hook case runs the real script with a throwaway HOME. The record is written to
`$HOME/.stackhawk/agent/sessions/$PPID.json`, and `$PPID` is this test process. The
no-jq cases run with a PATH that has no `jq` (both hooks have a fallback).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO_ROOT, "plugins/hawkscan/hooks")
SESSION_START = os.path.join(HOOKS, "session-start")
SKILL_ACTIVATED = os.path.join(HOOKS, "skill-activated")
DETECTION_COPIES = [
    "plugins/hawkscan/skills/hawkscan/references/agent-detection.md",
    "plugins/wingman/copilot-skills/hawkscan/references/agent-detection.md",
]

NO_JQ_TOOLS = [
    "bash", "cat", "date", "dirname", "grep", "head", "mkdir", "mv", "rm",
    "rmdir", "sed", "sleep", "stat", "tail",
]

# Agent variables that could leak in from the shell running the tests.
AGENT_VARS = [
    "CLAUDECODE", "CLAUDE_CODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION", "CURSOR_AGENT", "CURSOR_TRACE_ID", "CODEX_THREAD_ID",
    "GEMINI_API_KEY", "HAWK_AGENT", "_STACKHAWK_AGENT", "ANTHROPIC_MODEL",
    "OPENAI_MODEL", "GEMINI_MODEL", "AZURE_OPENAI_DEPLOYMENT",
]


@pytest.fixture
def no_jq_path(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in NO_JQ_TOOLS:
        found = shutil.which(tool)
        if found:
            os.symlink(found, bindir / tool)
    return str(bindir)


def clean_env(home, path=None, **extra):
    env = {k: v for k, v in os.environ.items() if k not in AGENT_VARS}
    env["HOME"] = str(home)
    if path:
        env["PATH"] = path
    env.update(extra)
    return env


def run_hook(hook, stdin, env):
    return subprocess.run(
        ["bash", hook], input=stdin, env=env, capture_output=True, text=True, check=True
    )


def record_path(home):
    return home / ".stackhawk" / "agent" / "sessions" / f"{os.getpid()}.json"


def read_record(home):
    with open(record_path(home)) as f:
        return json.load(f)


def session_start_payload(session_id):
    return json.dumps({
        "session_id": session_id,
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "SessionStart",
        "source": "startup",
    })


def skill_payload(session_id, skill="hawkscan:hawkscan"):
    body = {
        "cwd": "/tmp",
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": skill},
        "tool_response": {"success": True},
    }
    if session_id is not None:
        body["session_id"] = session_id
    return json.dumps(body)


@pytest.mark.parametrize("jq", [True, False], ids=["jq", "no-jq"])
def test_session_start_records_payload_session_id(tmp_path, no_jq_path, jq):
    env = clean_env(tmp_path, None if jq else no_jq_path, CLAUDE_CODE_SESSION_ID="env-id")
    out = run_hook(SESSION_START, session_start_payload("payload-id"), env)
    assert json.loads(out.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert read_record(tmp_path)["hostSessionId"] == "payload-id"


def test_session_start_falls_back_to_claude_code_session_id(tmp_path):
    env = clean_env(tmp_path, CLAUDE_CODE_SESSION_ID="env-id")
    run_hook(SESSION_START, "", env)
    assert read_record(tmp_path)["hostSessionId"] == "env-id"


def test_session_start_ignores_claude_session_id(tmp_path):
    env = clean_env(tmp_path, CLAUDE_SESSION_ID="not-a-claude-code-var")
    run_hook(SESSION_START, "", env)
    assert read_record(tmp_path)["hostSessionId"] == ""


@pytest.mark.parametrize("jq", [True, False], ids=["jq", "no-jq"])
def test_skill_activated_backfill_records_session_id(tmp_path, no_jq_path, jq):
    env = clean_env(tmp_path, None if jq else no_jq_path)
    run_hook(SKILL_ACTIVATED, skill_payload("payload-id"), env)
    record = read_record(tmp_path)
    assert record["hostSessionId"] == "payload-id"
    assert record["skillsActivated"] == ["hawkscan:hawkscan"]


def test_skill_activated_backfill_falls_back_to_env(tmp_path):
    env = clean_env(tmp_path, CLAUDE_CODE_SESSION_ID="env-id")
    run_hook(SKILL_ACTIVATED, skill_payload(None), env)
    assert read_record(tmp_path)["hostSessionId"] == "env-id"


@pytest.mark.parametrize("jq", [True, False], ids=["jq", "no-jq"])
def test_skill_activated_fills_empty_session_id(tmp_path, no_jq_path, jq):
    # A record written before the fix carries an empty hostSessionId.
    env = clean_env(tmp_path, None if jq else no_jq_path)
    run_hook(SESSION_START, "", env)
    assert read_record(tmp_path)["hostSessionId"] == ""
    run_hook(SKILL_ACTIVATED, skill_payload("payload-id"), env)
    record = read_record(tmp_path)
    assert record["hostSessionId"] == "payload-id"
    assert record["writer"] == "claude-hook"
    assert record["skillsActivated"] == ["hawkscan:hawkscan"]


@pytest.mark.parametrize("jq", [True, False], ids=["jq", "no-jq"])
def test_skill_activated_keeps_existing_session_id(tmp_path, no_jq_path, jq):
    env = clean_env(tmp_path, None if jq else no_jq_path)
    run_hook(SESSION_START, session_start_payload("first-id"), env)
    run_hook(SKILL_ACTIVATED, skill_payload("other-id", skill="api"), env)
    record = read_record(tmp_path)
    assert record["hostSessionId"] == "first-id"
    assert record["skillsActivated"] == ["api"]


def detection_block(rel):
    with open(os.path.join(REPO_ROOT, rel)) as f:
        text = f.read()
    blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1, f"{rel}: expected one bash block"
    return blocks[0]


def detect(rel, cwd, **env_vars):
    script = detection_block(rel) + '\nprintf "%s|%s" "$HAWK_AGENT" "$_STACKHAWK_AGENT"\n'
    env = clean_env(cwd, **env_vars)
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    out = subprocess.run(
        ["bash", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout
    hawk_agent, stackhawk_agent = out.split("|")
    assert hawk_agent == stackhawk_agent
    return hawk_agent


@pytest.mark.parametrize("rel", DETECTION_COPIES)
@pytest.mark.parametrize(
    "env_vars,expected",
    [
        ({"CLAUDECODE": "1"}, "claude-code"),
        ({"CLAUDECODE": "1", "ANTHROPIC_MODEL": "claude-opus-5-5"}, "claude-code:claude-opus-5-5"),
        ({"CURSOR_AGENT": "1"}, "cursor"),
        ({"CURSOR_TRACE_ID": "abc"}, "cursor"),
        ({"CODEX_THREAD_ID": "t-1"}, "codex"),
        ({"CLAUDE_CODE": "1"}, "unknown"),
        ({}, "unknown"),
    ],
    ids=["claudecode", "claudecode-model", "cursor-agent", "cursor-trace", "codex", "old-claude-code-var", "none"],
)
def test_detection_block_uses_real_agent_variables(tmp_path, rel, env_vars, expected):
    assert detect(rel, tmp_path, **env_vars) == expected


@pytest.mark.parametrize("rel", DETECTION_COPIES)
def test_detection_block_keeps_claude_dir_fallback(tmp_path, rel):
    (tmp_path / ".claude").mkdir()
    assert detect(rel, tmp_path) == "claude-code"
