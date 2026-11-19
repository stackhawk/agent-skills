"""The tag-selected release jobs, run as written against a scratch marketplace.

A new vX.Y.Z tag selects the exact source commit. validate exports that commit and dry-runs the
marketplace sync before any write job. update-marketplace repeats the export/sync and pushes once.
The marketplace sync lives in stackhawk/agent-skills-marketplace, so a version without --export
support must stop validation before a GitHub Release or marketplace write.

These tests take the `run` steps of a job from release.yml as they are, point every marketplace
URL at a scratch bare repository, and run the steps in order with `bash -eo pipefail`, as GitHub
Actions does. The role assumption is skipped, and the App token mint in the push step is replaced
with a local dummy token. The scratch marketplace holds a stand-in sync, not the real one:
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
TOKEN_MARKETPLACE = ("https://x-access-token:${token}"
                     "@github.com/stackhawk/agent-skills-marketplace.git")
JOB_CHECKOUT = "/tmp/marketplace"
VERSION = "9.8.7"
TAG = f"v{VERSION}"

# The steps that do not run here, by job. A renamed or removed step fails job_steps.
SKIPPED = {
    "validate": set(),
    "update-marketplace": {"Skip an older tag", "CI identity (tag publication role)"},
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
           "plugins": [{"name": n, "source": "./plugins/" + n, "version": args.tag[1:]}
                       for n in sorted(manifest["plugins"])]}
outputs = {
    ".claude-plugin/marketplace.json": catalog,
    ".github/plugin/marketplace.json": catalog,
    ".agents/plugins/marketplace.json": catalog,
    ".codex-plugin/marketplace.json": catalog,
    "sources.json": {"tag": args.tag, "sha": commit},
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
        if job == "update-marketplace" and step["name"] == "Push marketplace sync to main":
            token_command = ('token="$(biodome ci github-app-token --repository '
                             'agent-skills-marketplace --permission contents=write)"')
            assert script.count(token_command) == 2
            script = script.replace(token_command, "token=local-test-token")
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
    (work / "sources.json").write_text(json.dumps({"tag": "v9.8.6", "sha": "f" * 40}))
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
    git(path, "tag", TAG)
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
            "RELEASE_SHA": git(workspace, "rev-parse", TAG).decode().strip(),
            "GITHUB_OUTPUT": str(runner / "github-output"), "GITHUB_WORKSPACE": str(workspace),
            "SYNC_RECORD": str(tmp_path / "sync-record.jsonl")}


def records(tmp_path):
    path = tmp_path / "sync-record.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def report(results):
    return "\n".join(f"== {name}: exit {proc.returncode}\n{proc.stdout}{proc.stderr}" for name, proc in results)


def depends_on(job, ancestor, all_jobs):
    needs = all_jobs[job].get("needs", [])
    needs = [needs] if isinstance(needs, str) else needs
    return ancestor in needs or any(depends_on(n, ancestor, all_jobs) for n in needs)


def test_only_created_release_tags_can_reach_publication():
    all_jobs = jobs()
    with open(WORKFLOW) as f:
        workflow = yaml.safe_load(f)
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"push": {"tags": ["v*"]}}
    assert "claim" not in all_jobs and "tag" not in all_jobs
    assert "github.event.created == true" in all_jobs["resolve"]["if"]
    assert "github.ref_type == 'tag'" in all_jobs["resolve"]["if"]
    assert "github.event.deleted == false" in all_jobs["resolve"]["if"]
    for job in ("draft-release", "update-marketplace", "publish-release", "capture-baseline"):
        assert depends_on(job, "validate", all_jobs), job
        assert "github.event.created == true" in all_jobs[job]["if"], job
        assert "github.ref_type == 'tag'" in all_jobs[job]["if"], job
        assert "github.event.deleted == false" in all_jobs[job]["if"], job
        assert "startsWith(github.ref, 'refs/tags/v')" in all_jobs[job]["if"], job
    assert depends_on("publish-release", "update-marketplace", all_jobs)
    assert depends_on("capture-baseline", "publish-release", all_jobs)
    text = open(WORKFLOW).read()
    assert "biodome-rs ci version" not in text
    assert "git tag -f" not in text
    assert 'gh release create "$RELEASE_TAG" --draft --verify-tag --target "$RELEASE_SHA"' in text
    assert text.count('scripts/export-marketplace.py --ref "$RELEASE_SHA"') == 2
    assert text.count('--tag "$RELEASE_TAG" --export') == 2
    assert 'gh workflow run capture-baseline.yml -f tag="$RELEASE_TAG"' in text
    assert all_jobs["update-marketplace"]["outputs"]["published"]
    for job in ("update-marketplace", "capture-baseline"):
        assert "biodome-rs aws assume ci-agent-skills-publish" in str(all_jobs[job]["steps"])
        assert "ci-deploy-preprod" not in str(all_jobs[job]["steps"])


def test_marketplace_steps_guard_against_older_tags():
    steps = {step["name"]: step for step in jobs()["update-marketplace"]["steps"]}
    assert steps["Skip an older tag"]["if"] == "steps.order.outputs.value == 'older'"
    for name in ("Export the marketplace payload from the release commit",
                 "Sync marketplace from release tag", "CI identity (tag publication role)",
                 "Push marketplace sync to main"):
        assert steps[name]["if"] == "steps.order.outputs.value != 'older'", name
    assert "needs.validate.outputs.order != 'older'" in jobs()["draft-release"]["if"]
    assert "needs.update-marketplace.outputs.published == 'true'" in jobs()["publish-release"]["if"]
    push = steps["Push marketplace sync to main"]["run"]
    assert 'show origin/main:sources.json' in push
    assert 'if [ "$order" = older ]; then' in push
    assert "MARKETPLACE_TOKEN" not in push
    assert 'trap restore_public_remote EXIT' in push
    assert push.index('remote set-url origin https://github.com/stackhawk/agent-skills-marketplace.git') < push.index('unittest discover -s /tmp/marketplace/tests')


def test_validate_passes_the_format_2_export_of_the_commit_to_the_sync(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    main_before = git(marketplace, "rev-parse", "main")
    released = git(workspace, "rev-parse", TAG).decode().strip()
    (workspace / "unreleased-file").write_text("new main content\n")
    git(workspace, "add", "unreleased-file")
    git(workspace, "commit", "-q", "-m", "unreleased main")
    advanced_main = git(workspace, "rev-parse", "HEAD").decode().strip()
    git(workspace, "update-ref", "refs/remotes/origin/main", advanced_main)
    git(workspace, "checkout", "-q", "--detach", TAG)
    steps = job_steps("validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    assert [name for name, _ in results] == [name for name, _ in steps], report(results)
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    assert records(tmp_path) == [{"tag": TAG, "commit": released, "format": 2, "version": VERSION}]
    assert released != advanced_main
    assert git(workspace, "rev-parse", TAG).decode().strip() == released
    assert git(marketplace, "rev-parse", "main") == main_before, "validate pushed to the marketplace"


def test_validate_stops_the_release_when_the_sync_takes_no_export(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, OLD_SYNC)
    steps = job_steps("validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    failed, proc = results[-1]
    assert failed == "Dry-run the marketplace sync", report(results)
    assert "unrecognized arguments: --export" in proc.stderr, report(results)
    assert all(p.returncode == 0 for _, p in results[:-1]), report(results)
    assert git(workspace, "tag", "-l", TAG).decode().strip() == TAG


def test_update_marketplace_publishes_the_export_of_the_release_tag_once(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    released = git(workspace, "rev-parse", TAG).decode().strip()
    (workspace / "unreleased-file").write_text("new main content\n")
    git(workspace, "add", "unreleased-file")
    git(workspace, "commit", "-q", "-m", "unreleased main")
    git(workspace, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(workspace, "checkout", "-q", "--detach", TAG)
    first = run_steps(job_steps("update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace")),
                      workspace, job_env(tmp_path, workspace, "run-1"))
    assert all(proc.returncode == 0 for _, proc in first), report(first)

    assert git(marketplace, "log", "-1", "--format=%s", "main").decode().strip() == f"chore: sync agent-skills {TAG}"
    manifest = json.loads(git(marketplace, "show", "main:cursor-plugins/hawkscan/.cursor-plugin/plugin.json"))
    assert manifest["version"] == VERSION
    sources = json.loads(git(marketplace, "show", "main:sources.json"))
    assert sources == {"tag": TAG, "sha": released}
    catalog = json.loads(git(marketplace, "show", "main:.claude-plugin/marketplace.json"))
    assert {item["version"] for item in catalog["plugins"]} == {VERSION}
    skill = git(marketplace, "show", "main:plugins/hawkscan/skills/hawkscan/SKILL.md").decode()
    assert f"version: {VERSION}" in skill.split("---", 2)[1]
    assert "unreleased-file" not in git(marketplace, "ls-tree", "-r", "--name-only", "main").decode()
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


def test_marketplace_push_race_does_not_roll_back_a_newer_tag(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    steps = job_steps("update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace"))
    push_index = next(i for i, (name, _) in enumerate(steps) if name == "Push marketplace sync to main")
    env = job_env(tmp_path, workspace)
    prepared = run_steps(steps[:push_index], workspace, env)
    assert all(proc.returncode == 0 for _, proc in prepared), report(prepared)

    concurrent = tmp_path / "concurrent"
    subprocess.run(["git", "clone", "-q", str(marketplace), str(concurrent)],
                   env=git_env(), check=True)
    (concurrent / "sources.json").write_text(json.dumps({"tag": "v9.9.0", "sha": "e" * 40}))
    git(concurrent, "add", "sources.json")
    git(concurrent, "commit", "-q", "-m", "publish newer tag")
    git(concurrent, "push", "-q", "origin", "main")
    newer = git(marketplace, "rev-parse", "main")

    pushed = run_steps(steps[push_index:], workspace, env)
    assert all(proc.returncode == 0 for _, proc in pushed), report(pushed)
    assert "published=false" in (tmp_path / "run-1" / "github-output").read_text()
    assert git(marketplace, "rev-parse", "main") == newer
    assert json.loads(git(marketplace, "show", "main:sources.json"))["tag"] == "v9.9.0"
