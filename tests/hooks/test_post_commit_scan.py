"""The hawkscan post-commit-scan hook must fire on a real `git commit`, and only then.

The hook once read `.command` (the PostToolUse payload carries `.tool_input.command`),
then fell back to grepping the whole payload for `git commit`. The payload includes the
tool's output, so any command whose output mentioned "git commit" (a `git log`, a `cat` of
the hook itself) told the agent "Code committed at <sha>" and prompted a scan.

It must also never report a commit that was not just made: heredoc bodies are text, a
commit to another repo (`git -C`) is reported from that repo, and a repo whose HEAD reflog
has no commit from the last 10 minutes keeps the hook silent. A commit followed in the same
command by a push, checkout or pull --rebase is still reported.

Each case runs the real script against a throwaway git repo with a PostToolUse-shaped
payload. The no-jq cases run it with a PATH that has no `jq` (the hook has a fallback).
"""
import json
import os
import shutil
import subprocess
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "plugins/hawkscan/hooks/post-commit-scan")

# Tools the hook shells out to; a PATH holding only these has no jq.
NO_JQ_TOOLS = ["git", "grep", "sed", "tr", "cat", "head", "tail", "awk", "date", "bash", "env", "dirname"]

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


def git(path, *args, age_seconds=0):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_COMMITTER_DATE": f"{int(time.time()) - age_seconds} +0000",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path, message="add feature", age_seconds=0):
    """A git repo whose HEAD is a commit made `age_seconds` ago."""
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "commit", "-q", "--allow-empty", "-m", message, age_seconds=age_seconds)
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


@pytest.fixture
def stale_repo(tmp_path):
    return make_repo(tmp_path / "repo", age_seconds=3600)


@pytest.fixture
def no_jq_path(tmp_path):
    bin_dir = tmp_path / "nojq-bin"
    bin_dir.mkdir()
    for tool in NO_JQ_TOOLS:
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    return str(bin_dir)


def run_hook(repo, stdin, path=None, home=None):
    env = {**os.environ}
    if home is not None:
        env["HOME"] = str(home)
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
    "git -c user.name=a commit -m x",
    "git commit --amend --no-edit",
    "git commit -m \"$(cat <<'EOF'\nfix: handle it\n\nBody mentioning git log.\nEOF\n)\"",
    "make test\ngit commit -m x",
    "cat > notes.md <<'EOF'\nDon't forget\nEOF\ngit commit -m x",
    "# Don't stage the lockfile\ngit add src && git commit -m x",
    "echo \"shift << 2\"\ngit commit -m x",
    "# write it <<EOF\ngit commit -m x",
    "if ! git diff --cached --quiet; then git commit -m x; fi",
    "! git commit -m x",
    "time git commit -m x",
    "{ git add -A; git commit -m x; }",
    "for f in a; do git commit -m x; done",
]

HEREDOC_NOT_COMMITS = [
    "cat > /tmp/pr-body.md <<'EOF'\n- now fires only on a real `git commit`\nEOF",
    "cat > release.sh <<'EOF'\ngit add -A\ngit commit -m release\nEOF",
    "gh pr create --body-file - <<'EOF'\nDon't run `git commit` here\nEOF",
    "cat <<-EOF > release.sh\n\tgit commit -m release\n\tEOF",
    "gh pr comment 1 --body \"$(cat <<'EOF'\nA 6\" screen\ngit commit -m x\nEOF\n)\"",
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
    "ls # later: && git commit -m x",
    "# git commit -m x",
    "git --git-dir=.git commit -m x",
    "git --work-tree=. commit -m x",
    "GIT_DIR=.git git commit -m x",
    "GIT_WORK_TREE=. git commit -m x",
] + HEREDOC_NOT_COMMITS


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


@pytest.mark.parametrize(
    "dirname, target",
    [
        ("svc", "{other}"),
        ("svc", "../svc"),
        ("svc", "~/svc"),
        ("My Project", '"{other}"'),
        ("My Project", "'{other}'"),
        ("My Project", "~/My\\ Project"),
    ],
)
def test_dash_c_commit_reports_that_repos_head(tmp_path, repo, dirname, target):
    other = make_repo(tmp_path / dirname, message="other feature")
    command = f"git -C {target.format(other=other)} commit -m x"
    out = json.loads(run_hook(repo, payload(command), home=tmp_path))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert f"Code committed at {head_sha(other)}" in context
    assert head_sha(repo) not in context


@pytest.mark.parametrize(
    "command", ["git commit -m x", "git commit -m x; git status", "cd sub && git commit -m x"]
)
def test_silent_when_head_is_not_a_fresh_commit(stale_repo, command):
    """A failed commit or a commit elsewhere leaves an old HEAD, which is not reported."""
    assert run_hook(stale_repo, payload(command)) == ""


def test_silent_when_recent_reflog_entries_hold_no_commit(stale_repo):
    git(stale_repo, "checkout", "-q", "-b", "other")
    assert run_hook(stale_repo, payload("git commit -m x && git checkout -b other")) == ""


def test_chained_commit_then_slow_push_still_fires(tmp_path):
    repo = make_repo(tmp_path / "repo", age_seconds=300)
    out = json.loads(run_hook(repo, payload("git commit -m x && git push")))
    assert f"Code committed at {head_sha(repo)}" in out["hookSpecificOutput"]["additionalContext"]


def test_chained_commit_then_checkout_reports_the_commit(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "commit", "-q", "--allow-empty", "-m", "feature work")
    feature_sha = head_sha(repo)
    git(repo, "checkout", "-q", "-")
    out = json.loads(run_hook(repo, payload("git commit -m x && git checkout main")))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert f"Code committed at {feature_sha}" in context
    assert head_sha(repo) not in context
    assert run_hook(repo, payload("git status")) == ""
    assert run_hook(repo, payload("git log --oneline")) == ""


def test_chained_commit_then_pull_rebase_reports_rewritten_head(tmp_path):
    upstream = make_repo(tmp_path / "upstream")
    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(upstream), str(local))
    git(upstream, "commit", "-q", "--allow-empty", "-m", "upstream work")
    git(local, "commit", "-q", "--allow-empty", "-m", "mine")
    before_rebase = head_sha(local)
    git(local, "pull", "-q", "--rebase")
    assert head_sha(local) != before_rebase
    out = json.loads(run_hook(local, payload("git commit -m mine && git pull --rebase && git push")))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert f"Code committed at {head_sha(local)}" in context
    assert before_rebase not in context


@pytest.mark.parametrize("switch", ["checkout", "rebase-arg"])
def test_rebase_on_another_branch_does_not_replace_the_commit(repo, switch):
    base = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-b", "other")
    git(repo, "commit", "-q", "--allow-empty", "-m", "other work")
    git(repo, "checkout", "-q", base)
    git(repo, "commit", "-q", "--allow-empty", "-m", "base moves")
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "commit", "-q", "--allow-empty", "-m", "feature work")
    feature_sha = head_sha(repo)
    if switch == "checkout":
        git(repo, "checkout", "-q", "other")
        git(repo, "rebase", "-q", base)
        command = f"git commit -m f && git checkout other && git rebase {base}"
    else:
        git(repo, "rebase", "-q", base, "other")
        command = f"git commit -m f && git rebase {base} other"
    context = json.loads(run_hook(repo, payload(command)))["hookSpecificOutput"]["additionalContext"]
    assert f"Code committed at {feature_sha}" in context
    assert head_sha(repo) not in context


def test_fires_on_signed_commit_with_log_show_signature_on(tmp_path):
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("ssh-keygen is needed to sign a commit")
    key = tmp_path / "signing-key"
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, value in (
        ("gpg.format", "ssh"),
        ("user.signingkey", str(key)),
        ("commit.gpgsign", "true"),
        ("log.showSignature", "true"),
    ):
        git(repo, "config", name, value)
    git(repo, "commit", "-q", "--allow-empty", "-m", "signed")
    out = json.loads(run_hook(repo, payload("git commit -m signed")))
    assert f"Code committed at {head_sha(repo)}" in out["hookSpecificOutput"]["additionalContext"]


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


@pytest.mark.parametrize(
    "command",
    REAL_COMMITS[:6]
    + [
        "cat > notes.md <<'EOF'\nDon't forget\nEOF\ngit commit -m x",
        "cat <<-EOF\n\tgit commit -m x\n\tEOF\ngit commit -m y",
    ],
)
def test_without_jq_fires_on_real_git_commit(repo, no_jq_path, command):
    out = json.loads(run_hook(repo, payload(command), path=no_jq_path))
    assert f"Code committed at {head_sha(repo)}" in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("command", NOT_COMMITS[:5] + HEREDOC_NOT_COMMITS[:3])
def test_without_jq_silent_on_other_commands(repo, no_jq_path, command):
    stdin = payload(command, output="git commit -m x\n" + GIT_LOG_OUTPUT)
    assert run_hook(repo, stdin, path=no_jq_path) == ""
