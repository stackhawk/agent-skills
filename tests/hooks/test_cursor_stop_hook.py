"""The Cursor stop hook asks for one scan follow-up, and only after a normal turn end.

Cursor runs a `stop` hook when the agent loop ends and submits any `followup_message`
it prints as the next user message. The hook once ignored its input, so it asked for a
scan after the user pressed stop, after an error, after its own follow-up turn, and in
any repository with a code commit from the last hour, even with a clean tree.

The hook must print a follow-up only when all of these are true: the payload `status`
is `completed`, `loop_count` is 0, the working tree or index holds a code change, there
is no scan evidence, and it has not already asked in this conversation. Cursor resets
`loop_count` to 0 on every user message (desktop 3.9.16: `stopHookLoopCount`), so without
that record it would ask for a full scan again after every later turn. User-level hooks run from `~/.cursor/` and stop hooks of a
plugin run from the workspace root, so the hook finds the project from
`CURSOR_PROJECT_DIR` (or `workspace_roots[0]`), not from its working directory.

Each case runs the real script against a throwaway git repo with a stop payload shaped
like the one Cursor sends. The no-jq cases run it with a PATH that has no `jq`.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK_DIR = os.path.join(REPO_ROOT, "plugins/hawkscan/hooks/cursor")
HOOK = os.path.join(HOOK_DIR, "stop.sh")
WINGMAN_HOOK = os.path.join(REPO_ROOT, "cursor-plugins/wingman/hooks/cursor/stop.sh")

# Tools the hook shells out to; a PATH holding only these has no jq.
NO_JQ_TOOLS = ["git", "grep", "sed", "tr", "cat", "head", "tail", "sort", "wc", "bash", "env", "printf", "dirname", "mkdir", "mv"]

STATUSES = ["completed", "aborted", "error"]
LOOP_COUNTS = [0, 1]


def payload(status="completed", loop_count=0, roots=None, **extra):
    body = {
        "conversation_id": "c-1",
        "generation_id": "g-1",
        "model": "m",
        "hook_event_name": "stop",
        "cursor_version": "3.9.16",
        "workspace_roots": roots or [],
        "user_email": None,
        "transcript_path": None,
    }
    if status is not None:
        body["status"] = status
    if loop_count is not None:
        body["loop_count"] = loop_count
    body.update(extra)
    return json.dumps(body)


def git(path, *args, age_seconds=0):
    stamp = f"{int(time.time()) - age_seconds} +0000"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)


def make_repo(path, state):
    """A git repo in one of the states the hook must tell apart."""
    os.makedirs(os.path.join(path, "src"))
    with open(os.path.join(path, "src/app.py"), "w") as f:
        f.write("def health():\n    return 'ok'\n")
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    # The first commit is recent: the old hook treated any code commit from the last hour
    # as a change of this session, even on a clean tree.
    git(path, "commit", "-q", "-m", "init", age_seconds=60)
    if state == "clean":
        return
    if state == "old-commit":
        with open(os.path.join(path, "src/app.py"), "a") as f:
            f.write("# old change\n")
        git(path, "commit", "-q", "-am", "old change", age_seconds=7200)
        return
    if state in ("untracked", "ignored"):
        # A turn that only adds a file: untracked counts, ignored does not.
        if state == "ignored":
            with open(os.path.join(path, ".gitignore"), "w") as f:
                f.write("build/\n")
            git(path, "add", ".gitignore")
            git(path, "commit", "-q", "-m", "ignore build", age_seconds=7200)
        folder = "build" if state == "ignored" else "src"
        os.makedirs(os.path.join(path, folder), exist_ok=True)
        with open(os.path.join(path, folder, "new_endpoint.py"), "w") as f:
            f.write("def new():\n    return 1\n")
        return
    with open(os.path.join(path, "src/app.py"), "a") as f:
        f.write("# edit\n")
    if state == "staged":
        git(path, "add", "src/app.py")
    if state == "evidence":
        with open(os.path.join(path, "findings.json"), "w") as f:
            f.write("{}")


def no_jq_path(tmp_path):
    bindir = tmp_path / "nojq-bin"
    bindir.mkdir()
    for tool in NO_JQ_TOOLS:
        real = shutil.which(tool)
        assert real, f"test needs {tool} on PATH"
        os.symlink(real, bindir / tool)
    return str(bindir)


def run(hook, body, cwd, env_extra=None, path=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    if path:
        env["PATH"] = path
    env.update(env_extra or {})
    proc = subprocess.run(
        ["bash", hook], input=body, cwd=cwd, env=env, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def followup(out):
    assert out, "expected a followup_message, the hook printed nothing"
    data = json.loads(out)
    assert set(data) == {"followup_message"}, data
    return data["followup_message"]


@pytest.mark.parametrize("use_jq", [True, False], ids=["jq", "no-jq"])
@pytest.mark.parametrize("state", ["clean", "old-commit", "modified", "staged", "untracked", "ignored", "evidence"])
@pytest.mark.parametrize("loop_count", LOOP_COUNTS)
@pytest.mark.parametrize("status", STATUSES)
def test_payload_matrix(tmp_path, status, loop_count, state, use_jq):
    if use_jq and not shutil.which("jq"):
        pytest.skip("jq not installed")
    repo = tmp_path / "proj"
    make_repo(str(repo), state)
    out = run(HOOK, payload(status, loop_count), cwd=str(repo), path=None if use_jq else no_jq_path(tmp_path))
    should_fire = status == "completed" and loop_count == 0 and state in ("modified", "staged", "untracked")
    if should_fire:
        message = followup(out)
        assert "hawkscan skill" in message
        assert "1 file(s)" in message
    else:
        assert out == "", f"{status}/{loop_count}/{state} must stay silent, got: {out}"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json",
        payload(status=None),
        payload(loop_count=None),
        payload(status="completed", loop_count=-1),
    ],
    ids=["empty", "garbage", "no-status", "no-loop-count", "negative-loop-count"],
)
def test_unreadable_payload_stays_silent(tmp_path, body):
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    assert run(HOOK, body, cwd=str(repo)) == ""


def test_project_dir_env_wins_over_working_directory(tmp_path):
    # User-level hooks run from ~/.cursor/, which is not the project.
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    dot_cursor = tmp_path / "home" / ".cursor"
    dot_cursor.mkdir(parents=True)
    out = run(HOOK, payload(), cwd=str(dot_cursor), env_extra={"CURSOR_PROJECT_DIR": str(repo)})
    followup(out)


def test_workspace_roots_is_the_fallback_project_dir(tmp_path):
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    followup(run(HOOK, payload(roots=[str(repo)], conversation_id="c-jq"), cwd=str(elsewhere)))
    followup(run(HOOK, payload(roots=[str(repo)], conversation_id="c-nojq"), cwd=str(elsewhere),
                 path=no_jq_path(tmp_path)))


@pytest.mark.parametrize("use_jq", [True, False], ids=["jq", "no-jq"])
def test_one_follow_up_per_conversation(tmp_path, use_jq):
    if use_jq and not shutil.which("jq"):
        pytest.skip("jq not installed")
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    path = None if use_jq else no_jq_path(tmp_path)
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    followup(run(HOOK, payload(conversation_id="conv/../A b"), cwd=str(repo), path=path))
    # The user sends another message in the same conversation; the tree is still dirty.
    assert run(HOOK, payload(conversation_id="conv/../A b"), cwd=str(repo), path=path) == ""
    followup(run(HOOK, payload(conversation_id="conv-B"), cwd=str(repo), path=path))
    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert status_after == status_before, "the record must not show up in git status"


def test_without_a_conversation_id_every_completed_turn_may_ask(tmp_path):
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    followup(run(HOOK, payload(conversation_id=""), cwd=str(repo)))
    followup(run(HOOK, payload(conversation_id=""), cwd=str(repo)))


def test_the_record_stays_bounded(tmp_path):
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    record = subprocess.run(["git", "rev-parse", "--git-path", "stackhawk/cursor-stop-asked"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout.strip()
    record = os.path.join(repo, record)
    os.makedirs(os.path.dirname(record))
    with open(record, "w") as f:
        f.writelines(f"{i:040x}\n" for i in range(500))
    followup(run(HOOK, payload(conversation_id="fresh"), cwd=str(repo)))
    with open(record) as f:
        lines = f.read().splitlines()
    assert len(lines) <= 200
    assert run(HOOK, payload(conversation_id="fresh"), cwd=str(repo)) == ""


def test_an_unwritable_record_does_not_block_the_follow_up(tmp_path):
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    # A file where the record directory should be: the record cannot be written.
    blocker = subprocess.run(["git", "rev-parse", "--git-path", "stackhawk"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(repo, blocker), "w") as f:
        f.write("not a directory")
    followup(run(HOOK, payload(), cwd=str(repo)))


def test_outside_a_git_repo_stays_silent(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run(HOOK, payload(), cwd=str(plain), env_extra={"CURSOR_PROJECT_DIR": str(plain)}) == ""


def test_plugin_hook_command_runs_from_the_workspace_root(tmp_path):
    """The plugin hooks file must name a command that resolves from the workspace root.

    Both Cursor builds read for this change (CLI 2026.06.15, desktop 3.9.16) run a plugin
    `stop` hook with the workspace root as its working directory, replace
    `${CURSOR_PLUGIN_ROOT}` in the command with the plugin directory, and run the command
    through a shell with the payload on stdin. A `./hooks/...` path would resolve against
    the workspace and fail. This reproduces that offline; it is not a live Cursor run.
    """
    with open(os.path.join(HOOK_DIR, "plugin-hooks.json")) as f:
        config = json.load(f)
    entries = config["hooks"]["stop"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["loop_limit"] == 1
    assert "${CURSOR_PLUGIN_ROOT}" in entry["command"]
    plugin_root = tmp_path / "plugin cache" / "hawkscan"  # a space in the path must not break it
    shutil.copytree(os.path.join(REPO_ROOT, "plugins/hawkscan"), plugin_root, symlinks=True)
    command = entry["command"].replace("${CURSOR_PLUGIN_ROOT}", str(plugin_root))
    repo = tmp_path / "proj"
    make_repo(str(repo), "modified")
    script = f"{command} <<'CURSOR_HOOK_EOF'\n{payload()}\nCURSOR_HOOK_EOF"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["CURSOR_PROJECT_DIR"] = str(repo)
    proc = subprocess.run(["sh", "-c", script], cwd=str(repo), env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    followup(proc.stdout.strip())


def test_project_hooks_file_limits_the_hook_to_one_loop():
    with open(os.path.join(HOOK_DIR, "hooks.json")) as f:
        config = json.load(f)
    assert config["version"] == 1
    entries = config["hooks"]["stop"]
    assert entries == [{"command": ".cursor/hooks/stackhawk-stop.sh", "loop_limit": 1}]


def test_wingman_carries_an_identical_hook():
    with open(HOOK, "rb") as a, open(WINGMAN_HOOK, "rb") as b:
        assert a.read() == b.read()
    assert os.access(WINGMAN_HOOK, os.X_OK)
