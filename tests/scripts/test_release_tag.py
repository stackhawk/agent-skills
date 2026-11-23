"""Release tag input and marketplace order checks against synthetic Git refs."""

import json
import os
import subprocess
import sys

import pytest

from tests.git_env import git_env


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESOLVE = os.path.join(ROOT, "scripts", "ci", "release_tag.py")
ORDER = os.path.join(ROOT, "scripts", "ci", "marketplace_release_order.py")
SCRIPTS = ("scripts/ci/release_tag.py", "scripts/ci/marketplace_release_order.py")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=git_env(), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def tagged_repo(tmp_path):
    """main holds two commits. v9.8.0 names the first, which predates the release scripts, and
    v9.8.7 the second, which carries them. Both tags are on origin and in this checkout."""
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "content").write_text("old\n")
    git(repo, "add", "content")
    git(repo, "commit", "-q", "-m", "before the release scripts")
    git(repo, "tag", "v9.8.0")
    for script in SCRIPTS:
        (repo / script).parent.mkdir(parents=True, exist_ok=True)
        (repo / script).write_text("# stand-in\n")
    (repo / "content").write_text("released\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release source")
    bare = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "fetch", "-q", "origin", "main")
    git(repo, "tag", "v9.8.7")
    git(repo, "push", "-q", "origin", "v9.8.0", "v9.8.7")
    return repo


def run(repo, tmp_path, command="resolve", **changes):
    """release_tag.py as a Publish release job runs it: a workflow_dispatch run on main."""
    output = tmp_path / "github-output"
    env = git_env(identity=False, GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/heads/main",
                  GITHUB_SHA=git(repo, "rev-parse", "origin/main"), RELEASE_TAG="v9.8.7",
                  GITHUB_OUTPUT=str(output))
    env.update(changes)
    proc = subprocess.run([sys.executable, RESOLVE, command], cwd=repo, env=env,
                          capture_output=True, text=True)
    return proc, output


def test_release_tag_stays_on_exact_source_commit_after_main_advances(tagged_repo, tmp_path):
    source_sha = git(tagged_repo, "rev-parse", "HEAD")
    (tagged_repo / "content").write_text("unreleased main\n")
    git(tagged_repo, "commit", "-q", "-am", "unreleased source")
    git(tagged_repo, "push", "-q", "origin", "main")
    git(tagged_repo, "fetch", "-q", "origin", "main")
    proc, output = run(tagged_repo, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert output.read_text().splitlines() == ["tag=v9.8.7", "version=9.8.7", f"sha={source_sha}"]
    assert git(tagged_repo, "rev-parse", "origin/main") != source_sha


@pytest.mark.parametrize("changes", [
    {"GITHUB_EVENT_NAME": "push"},
    {"GITHUB_EVENT_NAME": "pull_request"},
    {"GITHUB_REF": "refs/heads/other"},
    {"GITHUB_REF": "refs/tags/v9.8.7"},
    {"RELEASE_TAG": ""},
    {"RELEASE_TAG": "claim/v9.8.7"},
    {"RELEASE_TAG": "abandoned/v9.8.7"},
    {"RELEASE_TAG": "refs/tags/v9.8.7"},
    {"RELEASE_TAG": "v9.8.7-rc.1"},
    {"RELEASE_TAG": "v09.8.7"},
    {"RELEASE_TAG": "v9.8"},
    {"RELEASE_TAG": "9.8.7"},
    {"RELEASE_TAG": "v9.8.7\nv9.8.8"},
    {"RELEASE_TAG": "v9.9.9"},
    {"GITHUB_OUTPUT": ""},
])
def test_other_events_bad_tags_and_missing_tags_fail_closed(tagged_repo, tmp_path, changes):
    proc, output = run(tagged_repo, tmp_path, **changes)
    assert proc.returncode != 0
    assert not output.exists()


def test_a_tag_missing_from_origin_is_rejected(tagged_repo, tmp_path):
    git(tagged_repo, "tag", "v9.8.8")
    proc, _ = run(tagged_repo, tmp_path, RELEASE_TAG="v9.8.8")
    assert proc.returncode != 0
    assert "missing from origin" in proc.stderr


def test_moved_tag_is_rejected(tagged_repo, tmp_path):
    source_sha = git(tagged_repo, "rev-parse", "HEAD")
    (tagged_repo / "content").write_text("new content\n")
    git(tagged_repo, "commit", "-q", "-am", "new source")
    git(tagged_repo, "tag", "-f", "v9.8.7")
    git(tagged_repo, "push", "-q", "--force", "origin", "v9.8.7")
    git(tagged_repo, "tag", "-f", "v9.8.7", source_sha)
    proc, _ = run(tagged_repo, tmp_path)
    assert proc.returncode != 0
    assert "no longer points" in proc.stderr


def test_verify_accepts_the_commit_that_resolve_chose_and_rejects_a_moved_tag(tagged_repo, tmp_path):
    source_sha = git(tagged_repo, "rev-parse", "HEAD")
    proc, _ = run(tagged_repo, tmp_path, "verify", RELEASE_SHA=source_sha)
    assert proc.returncode == 0, proc.stderr
    (tagged_repo / "content").write_text("new content\n")
    git(tagged_repo, "commit", "-q", "-am", "new source")
    git(tagged_repo, "tag", "-f", "v9.8.7")
    git(tagged_repo, "push", "-q", "--force", "origin", "v9.8.7")
    proc, _ = run(tagged_repo, tmp_path, "verify", RELEASE_SHA=source_sha)
    assert proc.returncode != 0
    assert "no longer points" in proc.stderr
    proc, _ = run(tagged_repo, tmp_path, "verify", RELEASE_SHA="not-a-sha")
    assert proc.returncode != 0


def test_annotated_tag_resolves_peeled_commit(tagged_repo, tmp_path):
    git(tagged_repo, "tag", "-a", "v9.8.8", "-m", "release")
    git(tagged_repo, "push", "-q", "origin", "v9.8.8")
    proc, output = run(tagged_repo, tmp_path, RELEASE_TAG="v9.8.8")
    assert proc.returncode == 0, proc.stderr
    assert output.read_text().splitlines() == ["tag=v9.8.8", "version=9.8.8",
                                               f"sha={git(tagged_repo, 'rev-parse', 'HEAD')}"]


def test_tag_not_reachable_from_main_is_rejected(tagged_repo, tmp_path):
    git(tagged_repo, "checkout", "-q", "--orphan", "other")
    git(tagged_repo, "rm", "-q", "-rf", ".")
    for script in SCRIPTS:
        (tagged_repo / script).parent.mkdir(parents=True, exist_ok=True)
        (tagged_repo / script).write_text("# stand-in\n")
    (tagged_repo / "content").write_text("branch only\n")
    git(tagged_repo, "add", "-A")
    git(tagged_repo, "commit", "-q", "-m", "branch source")
    git(tagged_repo, "tag", "v9.8.9")
    git(tagged_repo, "push", "-q", "origin", "v9.8.9")
    proc, _ = run(tagged_repo, tmp_path, RELEASE_TAG="v9.8.9")
    assert proc.returncode != 0
    assert "no longer points" not in proc.stderr


def test_a_tag_that_predates_the_release_scripts_is_rejected(tagged_repo, tmp_path):
    proc, output = run(tagged_repo, tmp_path, RELEASE_TAG="v9.8.0")
    assert proc.returncode != 0
    assert "tagged before Publish release existed" in proc.stderr
    assert not output.exists()


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
