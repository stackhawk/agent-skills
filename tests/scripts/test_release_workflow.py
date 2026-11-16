"""The release jobs of .github/workflows/release.yml, run as written against a scratch marketplace.

Every merge to main is a release. Its validate job exports the payload of the commit and dry-runs
the marketplace sync on it with --export, before claim takes a number. update-marketplace exports
the payload of the release tag, syncs it, and pushes it to marketplace main. The sync lives in
stackhawk/agent-skills-marketplace, so a marketplace whose sync does not take --export (the sync
before export format 2) must stop the release in validate, before claim, with no tag left.

These tests take the `run` steps of a job from release.yml as they are, point every marketplace
URL at a scratch bare repository, and run the steps in order with `bash -eo pipefail`, as GitHub
Actions does. Only the steps in SKIPPED, which need the runner's AWS role or a GitHub App token, do
not run. The scratch marketplace holds a stand-in sync, not the real one:
  - OLD_SYNC takes only --source-repo and --tag, as the marketplace sync before --export did;
  - FORMAT_2_SYNC checks what the release gives it (the tag names the commit; the export is format 2
    of that commit and version; Cursor installs hawkscan from cursor-plugins/hawkscan and wingman
    from bundles/wingman) and writes the export into the marketplace with the catalogs that the
    release stages. So the steps after it (the marketplace tests, the layout check with the
    installers, the staging script, the push) run on a real payload.
The real sync and its own checks are tested in the marketplace repository.
"""
import json
import os
import subprocess

import pytest
import yaml

from tests.git_env import git_env
from tests.scripts.test_marketplace_export import git, snapshot_working_tree

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "release.yml")
PUBLIC_MARKETPLACE = "https://github.com/stackhawk/agent-skills-marketplace.git"
TOKEN_MARKETPLACE = ("https://x-access-token:${MARKETPLACE_TOKEN}"
                     "@github.com/stackhawk/agent-skills-marketplace.git")
JOB_CHECKOUT = "/tmp/marketplace"
VERSION = "9.8.7"
TAG = f"v{VERSION}"

# The steps that do not run here, by job. A renamed or removed step fails job_steps.
SKIPPED = {
    "validate": set(),
    "update-marketplace": {"CI identity (ci-deploy-preprod)", "Marketplace App token"},
}

OLD_SYNC = '''\
"""The marketplace sync before export format 2: it takes no --export."""
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--source-repo", required=True)
parser.add_argument("--tag", required=True)
parser.parse_args()
'''

FORMAT_2_SYNC = '''\
"""A stand-in for the format-2 marketplace sync. It checks what the release gives it, records it
in $SYNC_RECORD, and writes the export into this checkout with the catalogs the release stages."""
import argparse
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTED = ("plugins", "bundles", "cursor-plugins", "install", ".cursor-plugin")

parser = argparse.ArgumentParser()
parser.add_argument("--source-repo", required=True)
parser.add_argument("--tag", required=True)
parser.add_argument("--export", required=True)
args = parser.parse_args()

commit = subprocess.run(["git", "-C", args.source_repo, "rev-parse", args.tag + "^{commit}"],
                        capture_output=True, text=True, check=True).stdout.strip()
with open(os.path.join(args.export, "export-manifest.json")) as f:
    manifest = json.load(f)
assert manifest["format"] == 2, manifest["format"]
assert manifest["source"]["commit"] == commit, (manifest["source"], commit)
assert manifest["version"] == args.tag[1:], (manifest["version"], args.tag)
assert manifest["cursor"]["hawkscan"] == "cursor-plugins/hawkscan", manifest["cursor"]
assert manifest["cursor"]["wingman"] == "bundles/wingman", manifest["cursor"]

for name in EXPORTED + ("skills",):
    shutil.rmtree(os.path.join(ROOT, name), ignore_errors=True)
for name in EXPORTED:
    shutil.copytree(os.path.join(args.export, name), os.path.join(ROOT, name), symlinks=True)
catalog = {"name": "stackhawk", "owner": {"name": "StackHawk"},
           "plugins": [{"name": n, "source": "./plugins/" + n} for n in sorted(manifest["plugins"])]}
outputs = {
    ".claude-plugin/marketplace.json": catalog,
    ".github/plugin/marketplace.json": catalog,
    ".agents/plugins/marketplace.json": catalog,
    ".codex-plugin/marketplace.json": catalog,
    "sources.json": {"tag": args.tag, "commit": commit},
    "skills/stand-in.json": {"tag": args.tag},
}
for rel, data in outputs.items():
    os.makedirs(os.path.dirname(os.path.join(ROOT, rel)), exist_ok=True)
    with open(os.path.join(ROOT, rel), "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\\n")
with open(os.environ["SYNC_RECORD"], "a") as f:
    f.write(json.dumps({"tag": args.tag, "commit": commit, "format": manifest["format"],
                        "version": manifest["version"]}) + "\\n")
'''

STAND_IN_TESTS = '''\
import unittest


class StandIn(unittest.TestCase):
    def test_the_stand_in_marketplace_has_tests(self):
        pass
'''


def jobs():
    with open(WORKFLOW) as f:
        return yaml.safe_load(f)["jobs"]


def job_steps(job, marketplace_url, checkout):
    """(name, script) of every `run` step of the job, with the marketplace URLs and checkout replaced."""
    steps = jobs()[job]["steps"]
    missing = SKIPPED[job] - {step.get("name") for step in steps}
    assert not missing, f"release.yml {job} has no step {sorted(missing)}"
    picked = []
    checkout_used = False
    for step in steps:
        if "run" not in step or step["name"] in SKIPPED[job]:
            continue
        checkout_used = checkout_used or JOB_CHECKOUT in step["run"]
        script = (step["run"].replace(TOKEN_MARKETPLACE, marketplace_url)
                  .replace(PUBLIC_MARKETPLACE, marketplace_url).replace(JOB_CHECKOUT, checkout))
        assert "github.com/stackhawk/agent-skills-marketplace" not in script, (job, step["name"])
        # Check the workflow text, not the substituted script: on Linux tmp_path is under /tmp/.
        assert "/tmp/" not in step["run"].replace(JOB_CHECKOUT, ""), (job, step["name"])
        picked.append((step["name"], script))
    assert checkout_used == (job == "update-marketplace"), f"release.yml {job} moved its marketplace checkout"
    return picked


def run_steps(steps, workspace, env):
    """Runs the steps in order and stops at the first that fails. Returns (name, process) of each run."""
    results = []
    for name, script in steps:
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                              cwd=workspace, env=env, capture_output=True, text=True, timeout=600,
                              check=False)
        results.append((name, proc))
        if proc.returncode != 0:
            break
    return results


def scratch_marketplace(tmp_path, sync):
    """A bare marketplace repository whose main holds the stand-in sync and one test."""
    work = tmp_path / "marketplace-source"
    (work / "scripts").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "scripts" / "sync-agent-skills.py").write_text(sync)
    (work / "tests" / "test_stand_in.py").write_text(STAND_IN_TESTS)
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "stand-in marketplace")
    bare = tmp_path / "marketplace.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], env=git_env(), check=True)
    return bare


@pytest.fixture(scope="module")
def source_repo(tmp_path_factory):
    path = tmp_path_factory.mktemp("release-source") / "agent-skills"
    path.mkdir()
    snapshot_working_tree(path)
    return path


@pytest.fixture
def workspace(source_repo, tmp_path):
    """The runner's checkout of the merged commit, with LF line endings as on the Linux runner."""
    path = tmp_path / "workspace"
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=input", "--no-local",
                    str(source_repo), str(path)], env=git_env(), check=True)
    return path


def job_env(tmp_path, workspace, run="run-1"):
    """The environment of one job run. GitHub Actions empties RUNNER_TEMP for every job, so each
    run gets its own; the sync record is shared, so a test sees every sync of every run."""
    runner = tmp_path / run
    (runner / "runner-temp").mkdir(parents=True)
    (runner / "home").mkdir()
    return {**git_env(identity=False), "HOME": str(runner / "home"), "PYTHONDONTWRITEBYTECODE": "1",
            "RELEASE_VERSION": VERSION, "RELEASE_TAG": TAG, "RUNNER_TEMP": str(runner / "runner-temp"),
            "GITHUB_WORKSPACE": str(workspace), "SYNC_RECORD": str(tmp_path / "sync-record.jsonl")}


def records(tmp_path):
    path = tmp_path / "sync-record.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def report(results):
    return "\n".join(f"== {name}: exit {proc.returncode}\n{proc.stdout}{proc.stderr}" for name, proc in results)


def depends_on(job, ancestor, all_jobs):
    needs = all_jobs[job].get("needs", [])
    needs = [needs] if isinstance(needs, str) else needs
    return ancestor in needs or any(depends_on(n, ancestor, all_jobs) for n in needs)


def test_every_release_write_waits_for_validate_through_claim():
    all_jobs = jobs()
    claim = all_jobs["claim"]
    assert "validate" in claim["needs"]
    assert "||" not in claim["if"]
    conditions = {term.strip() for term in claim["if"].split("&&")}
    assert {"!failure()", "!cancelled()"} <= conditions, claim["if"]
    for job in ("draft-release", "tag", "publish-release", "update-marketplace", "capture-baseline"):
        assert depends_on(job, "claim", all_jobs), job


def test_validate_passes_the_format_2_export_of_the_commit_to_the_sync(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    main_before = git(marketplace, "rev-parse", "main")
    steps = job_steps("validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    assert [name for name, _ in results] == [name for name, _ in steps], report(results)
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    head = git(workspace, "rev-parse", "HEAD").decode().strip()
    assert records(tmp_path) == [{"tag": TAG, "commit": head, "format": 2, "version": VERSION}]
    assert git(workspace, "tag", "-l", TAG) == b"", "the dry run left its tag"
    assert git(marketplace, "rev-parse", "main") == main_before, "validate pushed to the marketplace"


def test_validate_succeeds_after_the_deprecated_cursor_tree_is_removed(workspace, tmp_path):
    """The real validate steps must accept a source commit without the old rule tree.

    This models the follow-up commit and runs the release consumer rather than checking
    whether its workflow text happens to mention the retired generator.
    """
    subprocess.run(["git", "rm", "-r", "--ignore-unmatch", "cursor", "scripts/generate-cursor-rules.sh"],
                   cwd=workspace, env=git_env(), check=True, capture_output=True)
    if git(workspace, "diff", "--cached", "--name-only"):
        git(workspace, "commit", "-q", "-m", "remove deprecated Cursor rules")
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    steps = job_steps("validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    assert [name for name, _ in results] == [name for name, _ in steps], report(results)
    assert all(proc.returncode == 0 for _, proc in results), report(results)


def test_validate_stops_the_release_when_the_sync_takes_no_export(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, OLD_SYNC)
    steps = job_steps("validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    failed, proc = results[-1]
    assert failed == "Dry-run the marketplace sync", report(results)
    assert "unrecognized arguments: --export" in proc.stderr, report(results)
    assert all(p.returncode == 0 for _, p in results[:-1]), report(results)
    assert git(workspace, "tag", "-l", TAG) == b"", "the failed dry run left its tag"


def test_update_marketplace_publishes_the_export_of_the_release_tag_once(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    git(workspace, "tag", TAG, "HEAD")  # what the tag job does
    first = run_steps(job_steps("update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace")),
                      workspace, job_env(tmp_path, workspace, "run-1"))
    assert all(proc.returncode == 0 for _, proc in first), report(first)

    assert git(marketplace, "log", "-1", "--format=%s", "main").decode().strip() == f"chore: sync agent-skills {TAG}"
    manifest = json.loads(git(marketplace, "show", "main:cursor-plugins/hawkscan/.cursor-plugin/plugin.json"))
    assert manifest["version"] == VERSION
    listed = git(marketplace, "ls-tree", "-r", "--name-only", "main").decode().splitlines()
    assert not [p for p in listed if p.startswith(("plugins/hawkscan/.cursor-plugin/", "plugins/hawkscan/hooks/cursor/"))]
    assert ".cursor-plugin/marketplace.json" in listed and "install/install.sh" in listed

    main_after_first = git(marketplace, "rev-parse", "main")
    # A re-run of the job, as after a failure later in the release run: it must publish nothing new.
    second = run_steps(job_steps("update-marketplace", f"file://{marketplace}", str(tmp_path / "run-2" / "marketplace")),
                       workspace, job_env(tmp_path, workspace, "run-2"))
    assert all(proc.returncode == 0 for _, proc in second), report(second)
    assert f"Marketplace already contains {TAG}" in second[-1][1].stdout, report(second)
    assert git(marketplace, "rev-parse", "main") == main_after_first
    head = git(workspace, "rev-parse", "HEAD").decode().strip()
    assert [r["commit"] for r in records(tmp_path)] == [head, head]
