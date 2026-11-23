"""The release workflows, run as written against a scratch marketplace.

Two workflows split a release. release.yml runs on every merge to main: it numbers the commit,
validates it on a scratch copy, claims the number and tags the commit, and publishes nothing.
publish-release.yml is started by hand from main with a tag: it validates that tag's exact commit,
syncs the marketplace, publishes the GitHub Release and starts the eval baseline. The marketplace
sync lives in stackhawk/agent-skills-marketplace, so a version without --export support must stop
validation before a GitHub Release or marketplace write.

These tests take the `run` steps of a job from a workflow as they are, point every marketplace
URL at a scratch bare repository, and run the steps in order with `bash -eo pipefail`, as GitHub
Actions does. The role assumption is skipped, and the App token mint in the push step is replaced
with a local dummy token. The GitHub Release steps run against a stand-in `gh` that records its
calls. The scratch marketplace holds a stand-in sync, not the real one:
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
import re
import shutil
import subprocess

import pytest
import yaml

from tests.git_env import git_env
from tests.scripts.test_marketplace_export import git, snapshot_working_tree

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = os.path.join(REPO_ROOT, ".github", "workflows")
RELEASE = os.path.join(WORKFLOWS, "release.yml")
PUBLISH = os.path.join(WORKFLOWS, "publish-release.yml")
PUBLIC_MARKETPLACE = "https://github.com/stackhawk/agent-skills-marketplace.git"
TOKEN_MARKETPLACE = ("https://x-access-token:${token}"
                     "@github.com/stackhawk/agent-skills-marketplace.git")
JOB_CHECKOUT = "/tmp/marketplace"
VERSION = "9.8.7"
TAG = f"v{VERSION}"
REPOSITORY = "stackhawk/agent-skills"

# The steps that do not run here, by job. A renamed or removed step fails job_steps.
SKIPPED = {
    "validate": set(),
    "update-marketplace": {"CI identity (ci-deploy-preprod)"},
}
OLDER = "steps.order.outputs.value == 'older'"
NOT_OLDER = "steps.order.outputs.value != 'older'"

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


def load(path):
    with open(path) as f:
        return yaml.safe_load(f)


def triggers(workflow):
    return workflow.get("on", workflow.get(True))


def jobs(path):
    return load(path)["jobs"]


def job_steps(path, job, marketplace_url, checkout, order="newer"):
    """(name, script) of every `run` step of the job, with the marketplace URLs and checkout replaced.
    The only step conditions are the two on the release order; `order` is what the order step finds."""
    steps = jobs(path)[job]["steps"]
    skipped = SKIPPED[job]
    missing = skipped - {step.get("name") for step in steps}
    assert not missing, f"{os.path.basename(path)} {job} has no step {sorted(missing)}"
    picked = []
    checkout_used = False
    for step in steps:
        if "run" not in step or step["name"] in skipped:
            continue
        if "if" in step:
            assert step["if"] in (OLDER, NOT_OLDER), (job, step["name"], step["if"])
            if (step["if"] == OLDER) != (order == "older"):
                continue
        checkout_used = checkout_used or JOB_CHECKOUT in step["run"]
        script = (step["run"].replace(TOKEN_MARKETPLACE, marketplace_url)
                  .replace(PUBLIC_MARKETPLACE, marketplace_url).replace(JOB_CHECKOUT, checkout))
        if job == "update-marketplace" and step["name"] == "Push marketplace sync to main":
            token_command = ('token="$(biodome ci github-app-token --repository '
                             'agent-skills-marketplace --permission contents=write)"')
            assert script.count(token_command) == 1, "the token is minted once, at push time"
            script = script.replace(token_command, "token=local-test-token")
        assert "github.com/stackhawk/agent-skills-marketplace" not in script, (job, step["name"])
        # Check the workflow text, not the substituted script: on Linux tmp_path is under /tmp/.
        assert "/tmp/" not in step["run"].replace(JOB_CHECKOUT, ""), (job, step["name"])
        picked.append((step["name"], script))
    assert checkout_used == (job == "update-marketplace"), f"{os.path.basename(path)} {job} moved its marketplace checkout"
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


def scratch_marketplace(tmp_path, sync, pin="v9.8.6"):
    """A bare marketplace repository whose main holds the stand-in sync, one test and the published pin."""
    work = tmp_path / "marketplace-source"
    (work / "scripts").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "scripts" / "sync-agent-skills.py").write_text(sync)
    (work / "tests" / "test_stand_in.py").write_text(STAND_IN_TESTS)
    (work / "sources.json").write_text(json.dumps({"tag": pin, "sha": "f" * 40}))
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


def clone(source, path):
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=input", "--no-local", str(source), str(path)],
                   env=git_env(), check=True)
    return path


@pytest.fixture
def workspace(source_repo, tmp_path):
    """The runner's checkout of the merged commit, with LF line endings as on the Linux runner."""
    return clone(source_repo, tmp_path / "workspace")


@pytest.fixture
def tagged_workspace(source_repo, tmp_path):
    """The runner's checkout for Publish release: its origin carries the release tag."""
    origin = clone(source_repo, tmp_path / "origin")
    git(origin, "tag", TAG)
    return clone(origin, tmp_path / "workspace")


def advance_main(workspace):
    """A commit on main after the release tag, as a merge made while the release waits. Returns the
    tag's commit; the checkout is back on it, as the release job's checkout of the tag's commit."""
    released = git(workspace, "rev-parse", TAG).decode().strip()
    (workspace / "unreleased-file").write_text("new main content\n")
    git(workspace, "add", "unreleased-file")
    git(workspace, "commit", "-q", "-m", "unreleased main")
    git(workspace, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(workspace, "checkout", "-q", "--detach", TAG)
    return released


def job_env(tmp_path, workspace, run="run-1", sha=None):
    """The environment of one job run. GitHub Actions empties RUNNER_TEMP for every job, so each
    run gets its own; the sync record is shared, so a test sees every sync of every run."""
    runner = tmp_path / run
    (runner / "runner-temp").mkdir(parents=True)
    (runner / "home").mkdir()
    return {**git_env(identity=False), "HOME": str(runner / "home"), "PYTHONDONTWRITEBYTECODE": "1",
            "RELEASE_VERSION": VERSION, "RELEASE_TAG": TAG, "RUNNER_TEMP": str(runner / "runner-temp"),
            "RELEASE_SHA": sha or "", "GITHUB_OUTPUT": str(runner / "github-output"),
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


def steps_of(path, job):
    return {step["name"]: step for step in jobs(path)[job]["steps"]}


# ── What each workflow is allowed to do ──────────────────────────────────────────────────────────

def test_a_merge_numbers_and_tags_the_commit_and_publishes_nothing():
    workflow = load(RELEASE)
    all_jobs = workflow["jobs"]
    assert triggers(workflow) == {"push": {"branches": ["main"]}}
    assert set(all_jobs) == {"resolve", "validate", "claim", "tag"}
    claim = all_jobs["claim"]
    assert "validate" in claim["needs"]
    assert "||" not in claim["if"]
    conditions = {term.strip() for term in claim["if"].split("&&")}
    assert {"!failure()", "!cancelled()"} <= conditions, claim["if"]
    assert depends_on("tag", "claim", all_jobs)
    for job in ("claim", "tag"):
        assert "github.ref_name == 'main'" in all_jobs[job]["if"], job
        assert "biodome-rs aws assume ci-deploy-preprod" in str(all_jobs[job]["steps"]), job
    # No job can write anything a user sees: a tag is made with the App's token, not with GITHUB_TOKEN.
    for name, job in all_jobs.items():
        assert job["permissions"].get("contents") == "read", name
    text = open(RELEASE).read()
    for command in ("biodome-rs ci version resolve", "biodome-rs ci version claim", "biodome-rs ci version tag"):
        assert command in text, command
    for forbidden in ("gh release", "--draft", "capture-baseline", "--permission actions=write",
                      "github-app-token --repository agent-skills-marketplace", "push origin",
                      "ci-agent-skills-publish"):
        assert forbidden not in text, forbidden


def test_no_workflow_runs_on_a_tag_push():
    for name in sorted(os.listdir(WORKFLOWS)):
        if not name.endswith((".yml", ".yaml")):
            continue
        push = (triggers(load(os.path.join(WORKFLOWS, name))) or {}).get("push") or {}
        assert "tags" not in push and "tags-ignore" not in push, name
        assert "ci-agent-skills-publish" not in open(os.path.join(WORKFLOWS, name)).read(), name


def test_publish_runs_only_when_a_person_starts_it_with_a_tag():
    workflow = load(PUBLISH)
    all_jobs = workflow["jobs"]
    dispatch = triggers(workflow)
    assert list(dispatch) == ["workflow_dispatch"]
    assert list(dispatch["workflow_dispatch"]["inputs"]) == ["tag"]
    assert dispatch["workflow_dispatch"]["inputs"]["tag"]["required"] is True
    assert dispatch["workflow_dispatch"]["inputs"]["tag"]["type"] == "string"
    # The input reaches a job only through an env: it is never pasted into a script.
    text = open(PUBLISH).read()
    assert text.count("inputs.tag") == 1 and "RELEASE_TAG: ${{ inputs.tag }}" in text
    assert all("inputs." not in step.get("run", "") for job in all_jobs.values() for step in job["steps"])
    assert "ci-agent-skills-publish" not in text
    for name, job in all_jobs.items():
        assert job["if"].startswith("github.ref == 'refs/heads/main'"), name
        assert "environment" not in job, name
    assumed = {name for name, job in all_jobs.items() if "biodome-rs aws assume" in str(job["steps"])}
    assert assumed == {"update-marketplace", "capture-baseline"}
    assert {name for name, job in all_jobs.items() if job["permissions"].get("id-token") == "write"} == assumed
    for name in assumed:
        assert re.findall(r"aws assume (\S+)", str(all_jobs[name]["steps"])) == ["ci-deploy-preprod"], name
    assert all("biodome-rs ci version" not in str(job["steps"]) for job in all_jobs.values())
    assert "git tag" not in text and "git push" not in text.replace("git -C /tmp/marketplace push", "")


def test_nothing_is_published_before_the_tag_has_been_validated():
    all_jobs = jobs(PUBLISH)
    for job in ("draft-release", "update-marketplace", "publish-release", "capture-baseline"):
        assert depends_on(job, "validate", all_jobs), job
        assert depends_on(job, "resolve", all_jobs), job
    assert depends_on("update-marketplace", "draft-release", all_jobs)
    assert depends_on("publish-release", "update-marketplace", all_jobs)
    assert depends_on("capture-baseline", "publish-release", all_jobs)
    text = open(PUBLISH).read()
    assert text.count('scripts/export-marketplace.py --ref "$RELEASE_SHA"') == 2
    assert text.count('--tag "$RELEASE_TAG" --export') == 2
    assert 'gh workflow run capture-baseline.yml -f tag="$RELEASE_TAG"' in text
    for job in ("draft-release", "update-marketplace", "publish-release", "capture-baseline", "validate"):
        checkout = [s for s in all_jobs[job]["steps"] if s.get("uses", "").startswith("actions/checkout")][-1]
        assert checkout["with"]["ref"] == "${{ needs.resolve.outputs.sha }}", job
        assert "release_tag.py verify" in str(all_jobs[job]["steps"]), job


def test_marketplace_steps_guard_against_older_tags():
    steps = steps_of(PUBLISH, "update-marketplace")
    assert steps["Skip an older tag"]["if"] == "steps.order.outputs.value == 'older'"
    for name in ("Export the marketplace payload from the release commit",
                 "Sync marketplace from release tag", "Commit the marketplace sync",
                 "CI identity (ci-deploy-preprod)", "Push marketplace sync to main"):
        assert steps[name]["if"] == "steps.order.outputs.value != 'older'", name
    all_jobs = jobs(PUBLISH)
    assert "needs.validate.outputs.order != 'older'" in all_jobs["draft-release"]["if"]
    assert "needs.update-marketplace.outputs.published == 'true'" in all_jobs["publish-release"]["if"]
    assert all_jobs["update-marketplace"]["outputs"]["published"]
    push = steps["Push marketplace sync to main"]["run"]
    commit = steps["Commit the marketplace sync"]["run"]
    assert 'show FETCH_HEAD:sources.json' in push
    assert 'if [ "$order" = older ]; then' in push
    assert "MARKETPLACE_TOKEN" not in push
    # The commit is made in the clone that ran the marketplace's code, before the role and the token
    # exist, with git's hooks, fsmonitor, credential helpers and signing off. The token is used only
    # by a push from a pristine repository, straight to the URL: no git command of the push step
    # touches the clone, and the token is never written into a config.
    for setting in ("export GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null",
                    "export GIT_CONFIG_KEY_1=core.fsmonitor GIT_CONFIG_VALUE_1=false",
                    "export GIT_CONFIG_KEY_2=credential.helper GIT_CONFIG_VALUE_2=",
                    "export GIT_CONFIG_KEY_3=commit.gpgsign GIT_CONFIG_VALUE_3=false",
                    "export GIT_CONFIG_COUNT=4",
                    "export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_NOSYSTEM=1"):
        assert setting in commit, setting
        assert setting in push, setting  # the push step has the same hardening, for the pristine repository too
    assert commit.index("export GIT_CONFIG_COUNT=4") < commit.index("stage-marketplace-sync.sh") < commit.index("commit -q -m") < commit.index("git init -q")
    assert "git init -q --template= " in commit, "a global template would copy hooks into the new repository"
    assert push.index("export GIT_CONFIG_COUNT=4") < push.index("github-app-token")
    assert "github-app-token" not in commit and "x-access-token" not in commit
    assert "/tmp/marketplace" not in push and "remote set-url" not in push
    assert "x-access-token:${token}@" in push and 'push "https://' in push
    assert "unittest" not in push and "check-marketplace-layout" not in push and "rebase" not in push
    assert "re-run this job" in push
    names = list(steps)
    assert (names.index("Sync marketplace from release tag") < names.index("Commit the marketplace sync")
            < names.index("CI identity (ci-deploy-preprod)") < names.index("Push marketplace sync to main"))
    assert "needs.publish-release.outputs.newly == 'true'" in all_jobs["capture-baseline"]["if"]


def test_publish_checks_the_tag_with_the_same_steps_as_every_merge():
    shared = ("Stamp the release version", "Regenerate the wingman bundled skills", "Validate the stamped tree",
              "Verify the Cursor adapter is up to date")
    merge, publish = steps_of(RELEASE, "validate"), steps_of(PUBLISH, "validate")
    for name in shared:
        assert merge[name]["run"] == publish[name]["run"], name


# ── The merge-time validate job (release.yml) ────────────────────────────────────────────────────

def test_merge_validate_passes_the_format_2_export_of_the_commit_to_the_sync(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    main_before = git(marketplace, "rev-parse", "main")
    steps = job_steps(RELEASE, "validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    assert [name for name, _ in results] == [name for name, _ in steps], report(results)
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    head = git(workspace, "rev-parse", "HEAD").decode().strip()
    assert records(tmp_path) == [{"tag": TAG, "commit": head, "format": 2, "version": VERSION}]
    assert git(workspace, "tag", "-l", TAG) == b"", "the dry run left its tag"
    assert git(marketplace, "rev-parse", "main") == main_before, "validate pushed to the marketplace"


def test_merge_validate_stops_the_release_when_the_sync_takes_no_export(workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, OLD_SYNC)
    steps = job_steps(RELEASE, "validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, workspace, job_env(tmp_path, workspace))

    failed, proc = results[-1]
    assert failed == "Dry-run the marketplace sync", report(results)
    assert "unrecognized arguments: --export" in proc.stderr, report(results)
    assert all(p.returncode == 0 for _, p in results[:-1]), report(results)
    assert git(workspace, "tag", "-l", TAG) == b"", "the failed dry run left its tag"


# ── Publish release ──────────────────────────────────────────────────────────────────────────────

def test_publish_validate_passes_the_format_2_export_of_the_tag_commit_to_the_sync(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    main_before = git(marketplace, "rev-parse", "main")
    released = advance_main(tagged_workspace)
    steps = job_steps(PUBLISH, "validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, tagged_workspace, job_env(tmp_path, tagged_workspace, sha=released))

    assert [name for name, _ in results] == [name for name, _ in steps], report(results)
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    assert records(tmp_path) == [{"tag": TAG, "commit": released, "format": 2, "version": VERSION}]
    assert git(tagged_workspace, "rev-parse", "origin/main").decode().strip() != released
    assert git(tagged_workspace, "rev-parse", TAG).decode().strip() == released
    assert git(marketplace, "rev-parse", "main") == main_before, "validate pushed to the marketplace"
    assert (tmp_path / "run-1" / "github-output").read_text().strip() == "value=newer"


def test_publish_validate_stops_when_the_sync_takes_no_export(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, OLD_SYNC)
    released = git(tagged_workspace, "rev-parse", TAG).decode().strip()
    steps = job_steps(PUBLISH, "validate", f"file://{marketplace}", str(tmp_path / "unused"))
    results = run_steps(steps, tagged_workspace, job_env(tmp_path, tagged_workspace, sha=released))

    failed, proc = results[-1]
    assert failed == "Dry-run the marketplace sync", report(results)
    assert "unrecognized arguments: --export" in proc.stderr, report(results)
    assert all(p.returncode == 0 for _, p in results[:-1]), report(results)
    assert git(tagged_workspace, "tag", "-l", TAG).decode().strip() == TAG


def test_update_marketplace_publishes_the_export_of_the_release_tag_once(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    released = advance_main(tagged_workspace)
    first = run_steps(job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace")),
                      tagged_workspace, job_env(tmp_path, tagged_workspace, "run-1", released))
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
    listed = git(marketplace, "ls-tree", "-r", "--name-only", "main").decode().splitlines()
    assert "unreleased-file" not in listed
    assert not [p for p in listed if p.startswith(("plugins/hawkscan/.cursor-plugin/", "plugins/hawkscan/hooks/cursor/"))]
    assert ".cursor-plugin/marketplace.json" in listed and "install/install.sh" in listed
    assert "published=true" in (tmp_path / "run-1" / "github-output").read_text()

    main_after_first = git(marketplace, "rev-parse", "main")
    # A re-run of the job, as after a failure later in the run, or the tag that is already published:
    # it must publish nothing new.
    second = run_steps(job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-2" / "marketplace")),
                       tagged_workspace, job_env(tmp_path, tagged_workspace, "run-2", released))
    assert all(proc.returncode == 0 for _, proc in second), report(second)
    assert f"Marketplace already contains {TAG}" in second[-1][1].stdout, report(second)
    assert "published=true" in (tmp_path / "run-2" / "github-output").read_text()
    assert git(marketplace, "rev-parse", "main") == main_after_first
    assert [r["commit"] for r in records(tmp_path)] == [released, released]


def test_a_tag_older_than_the_published_pin_publishes_nothing(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC, pin="v9.9.0")
    released = advance_main(tagged_workspace)
    main_before = git(marketplace, "rev-parse", "main")
    steps = job_steps(PUBLISH, "validate", f"file://{marketplace}", str(tmp_path / "unused"))
    checked = run_steps(steps[:3], tagged_workspace, job_env(tmp_path, tagged_workspace, "run-1", released))
    assert all(proc.returncode == 0 for _, proc in checked), report(checked)
    assert (tmp_path / "run-1" / "github-output").read_text().strip() == "value=older"
    assert "::warning::Marketplace already has a newer release than " in checked[-1][1].stdout

    steps = job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-2" / "marketplace"),
                      order="older")
    assert [name for name, _ in steps][-2:] == ["Check marketplace release order", "Skip an older tag"]
    results = run_steps(steps, tagged_workspace, job_env(tmp_path, tagged_workspace, "run-2", released))
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    output = (tmp_path / "run-2" / "github-output").read_text().splitlines()
    assert output == ["value=older", "published=false"]
    assert git(marketplace, "rev-parse", "main") == main_before
    assert records(tmp_path) == []


def test_marketplace_push_race_does_not_roll_back_a_newer_tag(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    released = git(tagged_workspace, "rev-parse", TAG).decode().strip()
    steps = job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace"))
    push_index = next(i for i, (name, _) in enumerate(steps) if name == "Push marketplace sync to main")
    env = job_env(tmp_path, tagged_workspace, sha=released)
    prepared = run_steps(steps[:push_index], tagged_workspace, env)
    assert all(proc.returncode == 0 for _, proc in prepared), report(prepared)

    concurrent = tmp_path / "concurrent"
    subprocess.run(["git", "clone", "-q", str(marketplace), str(concurrent)],
                   env=git_env(), check=True)
    (concurrent / "sources.json").write_text(json.dumps({"tag": "v9.9.0", "sha": "e" * 40}))
    git(concurrent, "add", "sources.json")
    git(concurrent, "commit", "-q", "-m", "publish newer tag")
    git(concurrent, "push", "-q", "origin", "main")
    newer = git(marketplace, "rev-parse", "main")

    pushed = run_steps(steps[push_index:], tagged_workspace, env)
    assert all(proc.returncode == 0 for _, proc in pushed), report(pushed)
    assert "published=false" in (tmp_path / "run-1" / "github-output").read_text()
    assert git(marketplace, "rev-parse", "main") == newer
    assert json.loads(git(marketplace, "show", "main:sources.json"))["tag"] == "v9.9.0"


def test_a_push_that_loses_a_race_to_an_unrelated_commit_is_rerun_not_rebased(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    released = git(tagged_workspace, "rev-parse", TAG).decode().strip()
    steps = job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace"))
    push_index = next(i for i, (name, _) in enumerate(steps) if name == "Push marketplace sync to main")
    env = job_env(tmp_path, tagged_workspace, sha=released)
    prepared = run_steps(steps[:push_index], tagged_workspace, env)
    assert all(proc.returncode == 0 for _, proc in prepared), report(prepared)

    concurrent = tmp_path / "concurrent"
    subprocess.run(["git", "clone", "-q", str(marketplace), str(concurrent)], env=git_env(), check=True)
    (concurrent / "unrelated").write_text("another change\n")
    git(concurrent, "add", "unrelated")
    git(concurrent, "commit", "-q", "-m", "unrelated marketplace commit")
    git(concurrent, "push", "-q", "origin", "main")
    moved = git(marketplace, "rev-parse", "main")

    pushed = run_steps(steps[push_index:], tagged_workspace, env)
    assert pushed[-1][1].returncode != 0, report(pushed)
    assert "re-run this job" in pushed[-1][1].stdout
    assert "published" not in (tmp_path / "run-1" / "github-output").read_text()
    assert git(marketplace, "rev-parse", "main") == moved


def test_hooks_and_config_left_in_the_marketplace_clone_do_not_run_or_redirect_the_push(tagged_workspace, tmp_path):
    marketplace = scratch_marketplace(tmp_path, FORMAT_2_SYNC)
    released = git(tagged_workspace, "rev-parse", TAG).decode().strip()
    steps = job_steps(PUBLISH, "update-marketplace", f"file://{marketplace}", str(tmp_path / "run-1" / "marketplace"))
    commit_index = next(i for i, (name, _) in enumerate(steps) if name == "Commit the marketplace sync")
    env = job_env(tmp_path, tagged_workspace, sha=released)
    prepared = run_steps(steps[:commit_index], tagged_workspace, env)
    assert all(proc.returncode == 0 for _, proc in prepared), report(prepared)

    # What the marketplace's own code could leave behind in its clone: hooks (the pre-push hook is
    # given the push URL, which holds the token), a hooks path, an fsmonitor command, a credential
    # helper, a signing program and a rewrite of the URL the token is pushed to.
    clone = tmp_path / "run-1" / "marketplace"
    ran = tmp_path / "planted-code-ran"
    probe = tmp_path / "probe.sh"
    probe.write_text(f'#!/bin/sh\necho "$0 $*" >> {ran}\n')
    probe.chmod(0o755)
    hooks = clone / ".git" / "planted-hooks"
    hooks.mkdir()
    for directory in (hooks, clone / ".git" / "hooks"):
        for hook in ("pre-commit", "commit-msg", "post-commit", "pre-push"):
            (directory / hook).write_text(probe.read_text())
            (directory / hook).chmod(0o755)
    git(clone, "config", "core.hooksPath", str(hooks))
    git(clone, "config", "core.fsmonitor", str(probe))
    git(clone, "config", "credential.helper", f"!{probe}")
    git(clone, "config", "commit.gpgsign", "true")
    git(clone, "config", "gpg.program", str(probe))
    git(clone, "config", "url.file:///planted-redirect/.insteadOf", f"file://{marketplace}")
    # ... and in the runner user's own git config, which the marketplace's code can write as well:
    # a URL rewrite, a hooks path and a template that copies a pre-push hook into every new repository.
    template = tmp_path / "planted-template"
    (template / "hooks").mkdir(parents=True)
    (template / "hooks" / "pre-push").write_text(probe.read_text())
    (template / "hooks" / "pre-push").chmod(0o755)
    global_hooks = tmp_path / "planted-global-hooks"
    global_hooks.mkdir()
    for hook in ("pre-commit", "pre-push"):
        (global_hooks / hook).write_text(probe.read_text())
        (global_hooks / hook).chmod(0o755)
    global_config = tmp_path / "planted-gitconfig"
    global_config.write_text(f'[url "file:///planted-global-redirect/"]\n\tinsteadOf = file://{marketplace}\n'
                             f'[core]\n\thooksPath = {global_hooks}\n[init]\n\ttemplateDir = {template}\n')
    planted_env = {**env, "GIT_CONFIG_GLOBAL": str(global_config)}

    # The planted code does run, and the URL is rewritten, when git is not told otherwise.
    control = tmp_path / "control"
    shutil.copytree(clone, control, symlinks=True)
    subprocess.run(["git", "-C", str(control), "commit", "-q", "--allow-empty", "-m", "control"],
                   env=git_env(), capture_output=True, check=False)
    git(control, "status", "--short")
    planted = ran.read_text()
    assert "planted-hooks/commit-msg" in planted and str(probe) in planted
    assert "planted-redirect" in git(control, "ls-remote", "--get-url", f"file://{marketplace}").decode()
    ran.unlink()
    control_env = {**git_env(), "GIT_CONFIG_GLOBAL": str(global_config)}
    rewritten = subprocess.run(["git", "ls-remote", "--get-url", f"file://{marketplace}"], env=control_env,
                               capture_output=True, text=True, check=True).stdout
    assert "planted-global-redirect" in rewritten
    subprocess.run(["git", "init", "-q", str(tmp_path / "control-init")], env=control_env, check=True)
    assert (tmp_path / "control-init" / ".git" / "hooks" / "pre-push").exists()

    main_before = git(marketplace, "rev-parse", "main")
    results = run_steps(steps[commit_index:], tagged_workspace, planted_env)
    assert all(proc.returncode == 0 for _, proc in results), report(results)
    assert git(marketplace, "rev-parse", "main") != main_before, "the push did not happen"
    assert "published=true" in (tmp_path / "run-1" / "github-output").read_text()
    assert not ran.exists(), f"planted code ran: {ran.read_text() if ran.exists() else ''}"
    pushed_from = tmp_path / "run-1" / "runner-temp" / "marketplace-push"
    assert pushed_from.is_dir() and not (pushed_from / ".git" / "hooks" / "pre-push").exists()


# ── The GitHub Release steps, against a stand-in gh ──────────────────────────────────────────────

FAKE_GH = """\
#!/usr/bin/env bash
# Records every call. FAKE_LIST is what listing the releases of the repository returns, FAKE_LATEST
# the tag of the latest release (the call fails without one).
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"--method PATCH"*) ;;
  *"releases/latest"*) if [ -n "${FAKE_LATEST:-}" ]; then echo "$FAKE_LATEST"; else exit 1; fi ;;
  "api repos/"*"/releases --paginate"*) printf '%s' "${FAKE_LIST:-}" ;;
  "release create"*) ;;
  *) echo "unexpected gh call: $*" >&2; exit 2 ;;
esac
"""


def run_release_step(tmp_path, job, step, **env):
    """Runs one `run` step of a Publish release job with the stand-in gh first on PATH."""
    fake = tmp_path / "fake-bin"
    fake.mkdir(exist_ok=True)
    (fake / "gh").write_text(FAKE_GH)
    (fake / "gh").chmod(0o755)
    calls = tmp_path / "gh-calls"
    calls.write_text("")
    output = tmp_path / "step-output"
    output.write_text("")
    script = steps_of(PUBLISH, job)[step]["run"]
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                          env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "GH_CALLS": str(calls),
                               "GITHUB_REPOSITORY": REPOSITORY, "RELEASE_TAG": TAG, "RELEASE_SHA": "a" * 40,
                               "GITHUB_OUTPUT": str(output), **env},
                          capture_output=True, text=True, timeout=60, check=False)
    return proc, calls.read_text().splitlines(), output.read_text().splitlines()


def test_the_release_is_drafted_for_the_tag_with_notes_since_the_last_release(tmp_path):
    proc, calls, _ = run_release_step(tmp_path, "draft-release", "Draft the GitHub Release", FAKE_LATEST="v9.8.5")
    assert proc.returncode == 0, proc.stderr
    assert calls[-1] == (f"release create {TAG} --draft --verify-tag --target {'a' * 40} --title {TAG} "
                         "--generate-notes --notes-start-tag v9.8.5")


def test_the_first_release_is_drafted_without_a_start_tag(tmp_path):
    proc, calls, _ = run_release_step(tmp_path, "draft-release", "Draft the GitHub Release")
    assert proc.returncode == 0, proc.stderr
    assert calls[-1] == (f"release create {TAG} --draft --verify-tag --target {'a' * 40} --title {TAG} "
                         "--generate-notes")


def test_a_release_that_exists_is_not_drafted_again(tmp_path):
    proc, calls, _ = run_release_step(tmp_path, "draft-release", "Draft the GitHub Release", FAKE_LIST="12345")
    assert proc.returncode == 0, proc.stderr
    assert not [c for c in calls if c.startswith("release create")]


def test_a_draft_is_published_and_a_published_release_is_left_alone(tmp_path):
    proc, calls, output = run_release_step(tmp_path, "publish-release", "Publish the GitHub Release", FAKE_LIST="12345 true")
    assert proc.returncode == 0, proc.stderr
    assert calls[-1] == f"api --method PATCH repos/{REPOSITORY}/releases/12345 -F draft=false"
    assert output == ["newly=true"]
    proc, calls, output = run_release_step(tmp_path, "publish-release", "Publish the GitHub Release", FAKE_LIST="12345 false")
    assert proc.returncode == 0, proc.stderr
    assert "already published" in proc.stdout
    assert not [c for c in calls if "PATCH" in c]
    assert output == [], "the baseline would be captured again for a release that was already published"


def test_a_missing_release_stops_the_publish(tmp_path):
    proc, calls, output = run_release_step(tmp_path, "publish-release", "Publish the GitHub Release")
    assert proc.returncode != 0
    assert f"no GitHub Release for {TAG}" in proc.stdout
    assert not [c for c in calls if "PATCH" in c]
    assert output == []
