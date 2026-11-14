"""scripts/ci/stage-marketplace-sync.sh stages the marketplace sync outputs, or fails.

The release runs it twice: in validate, on a scratch clone of the marketplace after a dry-run
sync (nothing is committed), and in update-marketplace before the commit. So a sync that writes
outside the published paths, or does not write one of them, fails before a number is claimed.
"""
import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "ci", "stage-marketplace-sync.sh")
PATHS = ["plugins/hawkscan/SKILL.md", "bundles/wingman/README.md", "skills/hawkscan/SKILL.md",
         "install/install.sh", "sources.json", ".claude-plugin/marketplace.json",
         ".github/plugin/marketplace.json", ".agents/plugins/marketplace.json",
         ".codex-plugin/marketplace.json", ".cursor-plugin/marketplace.json"]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=ENV, check=True,
                          capture_output=True, text=True).stdout


def write(path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def marketplace(tmp_path):
    repo = tmp_path / "marketplace"
    write(repo / "scripts" / "sync-agent-skills.py", "# sync\n")
    write(repo / "README.md")
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main")
    return repo


def stage(repo):
    return subprocess.run(["bash", SCRIPT, str(repo)], capture_output=True, text=True)


def test_a_complete_sync_is_staged(marketplace):
    for rel in PATHS:
        write(marketplace / rel)
    proc = stage(marketplace)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(git(marketplace, "diff", "--cached", "--name-only").split()) == sorted(PATHS)


@pytest.mark.parametrize("missing", ["install/install.sh", ".cursor-plugin/marketplace.json"])
def test_a_sync_that_does_not_write_a_published_path_fails(marketplace, missing):
    for rel in PATHS:
        if rel != missing:
            write(marketplace / rel)
    proc = stage(marketplace)
    assert proc.returncode == 1
    assert missing.split("/")[0] in proc.stdout + proc.stderr


@pytest.mark.parametrize("stray", ["scripts/sync-agent-skills.py", "notes.txt"])
def test_a_sync_that_writes_elsewhere_fails(marketplace, stray):
    for rel in PATHS:
        write(marketplace / rel)
    write(marketplace / stray, "changed\n")
    proc = stage(marketplace)
    assert proc.returncode == 1
    assert "outside the staged paths" in proc.stdout + proc.stderr
