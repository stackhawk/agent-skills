"""The hawkscan post-commit-scan hook must fire on a real `git commit`, and only then.

The hook once read `.command` (the PostToolUse payload carries `.tool_input.command`),
then fell back to grepping the whole payload for `git commit`. The payload includes the
tool's output, so any command whose output mentioned "git commit" (a `git log`, a `cat` of
the hook itself) told the agent "Code committed at <sha>" and prompted a scan.

Each case runs the real script against a throwaway git repo with a PostToolUse-shaped
payload. The no-jq cases run it with a PATH that has no `jq` (the hook has a fallback).
"""
import json
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "plugins/hawkscan/hooks/post-commit-scan")

# Tools the hook shells out to; a PATH holding only these has no jq.
NO_JQ_TOOLS = ["git", "grep", "sed", "tr", "cat", "head", "bash", "env", "dirname"]

GIT_LOG_OUTPUT = (
    "d840d01 Code committed at d840d01\n"
    "ecc998e docs: how to run git commit with a message\n"
)


def payload(command, output="", **extra):
    body = {
        "session_id": "s",
        "cwd": "/tmp",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": output, "stderr": "", "interrupted": False},
    }
    body.update(extra)
    return json.dumps(body)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "add feature"]):
        subprocess.run(["git", *args], cwd=path, env=env, check=True)
    return path


@pytest.fixture
def no_jq_path(tmp_path):
    bin_dir = tmp_path / "nojq-bin"
    bin_dir.mkdir()
    for tool in NO_JQ_TOOLS:
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    return str(bin_dir)


def run_hook(repo, stdin, path=None):
    env = {**os.environ}
    if path is not None:
        env["PATH"] = path
    result = subprocess.run(
        [shutil.which("bash") or "bash", HOOK],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def head_sha(repo):
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()


REAL_COMMITS = [
    "git commit -m 'add feature'",
    'git commit -m "add feature"',
    "git commit",
    "git add -A && git commit -m 'add feature'",
    "git add -A; git commit -m x",
    "cd sub && git commit -am x",
    "GIT_AUTHOR_NAME=a git commit -m x",
    "git -C /tmp/repo commit -m x",
    "git -c user.name=a commit -m x",
    "git commit --amend --no-edit",
    "git commit -m \"$(cat <<'EOF'\nfix: handle it\n\nBody mentioning git log.\nEOF\n)\"",
    "make test\ngit commit -m x",
]

NOT_COMMITS = [
    "git log --oneline",
    "git status",
    "git diff HEAD",
    "cat plugins/hawkscan/hooks/post-commit-scan",
    "git commit-graph write",
    "git commit-tree HEAD^{tree}",
    "echo git commit",
    "echo 'run git commit when done'",
    'grep -rn "git commit" docs/',
    "git log --grep='git commit'",
    "git config alias.ci commit",
]


@pytest.mark.parametrize("command", REAL_COMMITS)
def test_fires_on_real_git_commit(repo, command):
    out = json.loads(run_hook(repo, payload(command)))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert f"Code committed at {head_sha(repo)}" in context


@pytest.mark.parametrize("command", NOT_COMMITS)
def test_silent_on_other_commands_even_when_output_mentions_git_commit(repo, command):
    # The tool output (what the old fallback grepped) mentions "git commit" in every case.
    stdin = payload(command, output="git commit -m x\n" + GIT_LOG_OUTPUT)
    assert run_hook(repo, stdin) == ""


def test_reproduction_git_log_whose_output_mentions_git_commit(repo):
    """Observed live: `git log` printed "Code committed at d840d01"."""
    assert run_hook(repo, payload("git log --oneline -5", output=GIT_LOG_OUTPUT)) == ""


def test_does_not_read_top_level_command(repo):
    """The command lives at .tool_input.command; a top-level `command` is not it."""
    stdin = json.dumps({"tool_name": "Bash", "command": "git commit -m x", "tool_input": {}})
    assert run_hook(repo, stdin) == ""


def test_no_command_field_is_silent(repo):
    assert run_hook(repo, json.dumps({"tool_name": "Bash", "tool_input": {}})) == ""
    assert run_hook(repo, "not json at all, mentions git commit") == ""
    assert run_hook(repo, "") == ""


def test_silent_outside_a_git_repo(tmp_path):
    assert run_hook(tmp_path, payload("git commit -m x")) == ""


def test_silent_when_scan_evidence_exists(repo):
    (repo / "findings.json").write_text("{}")
    assert run_hook(repo, payload("git commit -m x")) == ""


@pytest.mark.parametrize("command", REAL_COMMITS[:6])
def test_without_jq_fires_on_real_git_commit(repo, no_jq_path, command):
    out = json.loads(run_hook(repo, payload(command), path=no_jq_path))
    assert f"Code committed at {head_sha(repo)}" in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("command", NOT_COMMITS[:5])
def test_without_jq_silent_on_other_commands(repo, no_jq_path, command):
    stdin = payload(command, output="git commit -m x\n" + GIT_LOG_OUTPUT)
    assert run_hook(repo, stdin, path=no_jq_path) == ""
