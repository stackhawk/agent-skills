"""Release event and marketplace order checks against synthetic Git refs."""

import json
import os
import subprocess
import sys

import pytest

from tests.git_env import git_env


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESOLVE = os.path.join(ROOT, "scripts", "ci", "release_tag.py")
ORDER = os.path.join(ROOT, "scripts", "ci", "marketplace_release_order.py")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=git_env(), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def tagged_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "content").write_text("released\n")
    git(repo, "add", "content")
    git(repo, "commit", "-q", "-m", "release source")
    bare = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "fetch", "-q", "origin", "main")
    git(repo, "tag", "v9.8.7")
    git(repo, "push", "-q", "origin", "v9.8.7")
    return repo


def event(repo, tmp_path, **changes):
    output = tmp_path / "github-output"
    source_sha = git(repo, "rev-parse", "HEAD")
    env = git_env(identity=False, GITHUB_EVENT_NAME="push", GITHUB_REF_TYPE="tag",
                  GITHUB_EVENT_CREATED="true", GITHUB_EVENT_DELETED="false",
                  GITHUB_REF="refs/tags/v9.8.7", GITHUB_SHA=source_sha,
                  GITHUB_OUTPUT=str(output))
    env.update(changes)
    proc = subprocess.run([sys.executable, RESOLVE, "resolve"], cwd=repo, env=env,
                          capture_output=True, text=True)
    return proc, output


def test_release_tag_stays_on_exact_source_commit_after_main_advances(tagged_repo, tmp_path):
    source_sha = git(tagged_repo, "rev-parse", "HEAD")
    (tagged_repo / "content").write_text("unreleased main\n")
    git(tagged_repo, "commit", "-q", "-am", "unreleased source")
    git(tagged_repo, "push", "-q", "origin", "main")
    git(tagged_repo, "checkout", "-q", "--detach", source_sha)
    proc, output = event(tagged_repo, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert output.read_text().splitlines() == ["tag=v9.8.7", "version=9.8.7", f"sha={source_sha}"]
    assert git(tagged_repo, "rev-parse", "origin/main") != source_sha


@pytest.mark.parametrize("changes", [
    {"GITHUB_EVENT_NAME": "workflow_dispatch"},
    {"GITHUB_REF_TYPE": "branch", "GITHUB_REF": "refs/heads/main"},
    {"GITHUB_EVENT_CREATED": "false"},
    {"GITHUB_EVENT_DELETED": "true"},
    {"GITHUB_REF": "refs/tags/claim/v9.8.7"},
    {"GITHUB_REF": "refs/tags/v9.8.7-rc.1"},
    {"GITHUB_REF": "refs/tags/v09.8.7"},
    {"GITHUB_REF": "refs/tags/v9.8"},
    {"GITHUB_SHA": "0" * 40},
])
def test_non_release_events_and_bad_tags_fail_closed(tagged_repo, tmp_path, changes):
    proc, output = event(tagged_repo, tmp_path, **changes)
    assert proc.returncode != 0
    assert not output.exists()


def test_moved_tag_is_rejected(tagged_repo, tmp_path):
    source_sha = git(tagged_repo, "rev-parse", "HEAD")
    (tagged_repo / "content").write_text("new content\n")
    git(tagged_repo, "commit", "-q", "-am", "new source")
    git(tagged_repo, "tag", "-f", "v9.8.7")
    git(tagged_repo, "push", "-q", "--force", "origin", "v9.8.7")
    git(tagged_repo, "checkout", "-q", "--detach", source_sha)
    proc, _ = event(tagged_repo, tmp_path)
    assert proc.returncode != 0
    assert "no longer points" in proc.stderr


def test_annotated_tag_resolves_peeled_commit(tagged_repo, tmp_path):
    git(tagged_repo, "tag", "-a", "v9.8.8", "-m", "release")
    git(tagged_repo, "push", "-q", "origin", "v9.8.8")
    proc, output = event(tagged_repo, tmp_path, GITHUB_REF="refs/tags/v9.8.8")
    assert proc.returncode == 0, proc.stderr
    assert output.read_text().splitlines()[1] == "version=9.8.8"


def test_tag_not_reachable_from_main_is_rejected(tagged_repo, tmp_path):
    git(tagged_repo, "checkout", "-q", "--orphan", "other")
    git(tagged_repo, "rm", "-q", "-rf", ".")
    (tagged_repo / "content").write_text("branch only\n")
    git(tagged_repo, "add", "content")
    git(tagged_repo, "commit", "-q", "-m", "branch source")
    git(tagged_repo, "tag", "v9.8.9")
    git(tagged_repo, "push", "-q", "origin", "v9.8.9")
    proc, _ = event(tagged_repo, tmp_path, GITHUB_REF="refs/tags/v9.8.9")
    assert proc.returncode != 0


def check_order(tmp_path, current_tag, current_sha, tag, sha):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"tag": current_tag, "sha": current_sha}))
    return subprocess.run([sys.executable, ORDER, str(sources), tag, sha],
                          capture_output=True, text=True)


def test_marketplace_order_allows_current_retry_and_newer_tag(tmp_path):
    sha = "a" * 40
    assert check_order(tmp_path, "v9.8.7", sha, "v9.8.7", sha).stdout.strip() == "current"
    assert check_order(tmp_path, "v9.8.7", sha, "v9.9.0", "b" * 40).stdout.strip() == "newer"


def test_marketplace_order_refuses_rollback_and_moved_source(tmp_path):
    sha = "a" * 40
    assert check_order(tmp_path, "v9.9.0", sha, "v9.8.7", "b" * 40).stdout.strip() == "older"
    proc = check_order(tmp_path, "v9.8.7", sha, "v9.8.7", "b" * 40)
    assert proc.returncode != 0
    assert "different commit" in proc.stderr
