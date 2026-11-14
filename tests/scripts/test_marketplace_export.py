"""The marketplace export: the release payload that stackhawk/agent-skills-marketplace consumes.

`scripts/export-marketplace.py` reads one commit of this repository and writes what the
marketplace publishes from it: a Claude-oriented snapshot of each plugin, the complete wingman
bundle for Copilot, Codex and Cursor, the Cursor catalog, and the Cursor installers.
`scripts/check-marketplace-layout.py` checks such a tree, and the release runs it on the synced
marketplace before the push.

The defect these tests guard: the marketplace once copied all of `plugins/wingman` into the
Claude-listed snapshot. Cursor imports Claude Code plugins, so a Claude Code user with wingman
(and its hawkscan dependency) got the router rule and the stop hook twice.

Every export here comes from a git snapshot of this working tree, so the tests see uncommitted
changes the way a commit would carry them.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(REPO_ROOT, "scripts", "export-marketplace.py")
CHECK = os.path.join(REPO_ROOT, "scripts", "check-marketplace-layout.py")
VERSION = "9.8.7"

# What the Claude-oriented snapshot of a plugin may leave out of its source folder. Owned by
# this test, not by the exporter, so a change that drops more files from a Claude snapshot fails.
CLAUDE_SNAPSHOT_OMITS = {
    "wingman": (".github", "copilot-skills", ".cursor-plugin", "rules", "hooks/cursor"),
}
INSTALLER_FILES = ("install.sh", "install.ps1", "cursor-legacy-rules.txt")
BUNDLED_SKILLS = {"hawkscan", "stackhawk-api", "stackhawk-data-seed", "stackhawk-optimize"}
INSTALLERS = ["sh"] + (["ps1"] if shutil.which("pwsh") else [])


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAYOUT = load(CHECK, "check_marketplace_layout")

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], env=GIT_ENV, check=True,
                          capture_output=True).stdout


def snapshot_working_tree(dest):
    """Commit the tracked and new (not ignored) files of this checkout into a fresh repository."""
    listed = git(REPO_ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in sorted({p.decode() for p in listed.split(b"\0") if p}):
        source = os.path.join(REPO_ROOT, rel)
        if not os.path.lexists(source):
            continue
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.islink(source):
            os.symlink(os.readlink(source), target)
        else:
            shutil.copy2(source, target)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "snapshot")


def run_export(source, dest, version=VERSION, ref="HEAD", check=True):
    proc = subprocess.run(
        ["python3", EXPORT, "--source-repo", str(source), "--ref", ref, "--version", version,
         "--dest", str(dest)],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if check:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def files_under(root):
    """relative path -> (executable, bytes) for every regular file; symlinks are an error."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            assert not os.path.islink(full), f"symlink in export: {full}"
        for name in filenames:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                found[os.path.relpath(full, root)] = (bool(os.stat(full).st_mode & stat.S_IXUSR), f.read())
    return found


def without(files, omitted):
    return {rel: v for rel, v in files.items()
            if not any(rel == o or rel.startswith(o + "/") for o in omitted)}


@pytest.fixture(scope="session")
def source_repo(tmp_path_factory):
    path = tmp_path_factory.mktemp("source") / "agent-skills"
    path.mkdir()
    snapshot_working_tree(path)
    return path


@pytest.fixture(scope="session")
def release_tree(source_repo, tmp_path_factory):
    """The commit as the release validates it: stamped, with the wingman bundle regenerated."""
    tree = tmp_path_factory.mktemp("release")
    archive = git(source_repo, "archive", "--format=tar", "HEAD")
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
    for command in (["bash", "scripts/bump-version.sh", VERSION], ["bash", "scripts/generate-wingman-skills.sh"]):
        subprocess.run(command, cwd=tree, check=True, capture_output=True)
    return tree


@pytest.fixture(scope="session")
def exported(source_repo, tmp_path_factory):
    dest = tmp_path_factory.mktemp("export") / "out"
    run_export(source_repo, dest)
    return dest


@pytest.fixture(scope="session")
def claude_catalog(source_repo):
    with open(source_repo / ".claude-plugin" / "marketplace.json") as f:
        return {entry["name"]: entry["source"].removeprefix("./") for entry in json.load(f)["plugins"]}


@pytest.fixture
def scratch(exported, tmp_path):
    """A copy of the export that a test may change."""
    copy = tmp_path / "copy"
    shutil.copytree(exported, copy, symlinks=True)
    return copy


def errors_of(root, version=VERSION, run_installers=False):
    return LAYOUT.check(str(root), version=version, run_installers=run_installers)


def assert_error(errors, *needles):
    text = "\n".join(errors)
    for needle in needles:
        assert needle in text, f"expected an error with {needle!r}, got:\n{text}"


# ─── The export ───

def test_export_passes_the_layout_check(exported):
    assert errors_of(exported) == []


def test_claude_wingman_carries_no_cursor_or_copilot_files(exported):
    wingman = exported / "plugins" / "wingman"
    for rel in (".cursor-plugin", "rules", "hooks", "copilot-skills", ".github", "skills"):
        assert not (wingman / rel).exists(), rel
    assert sorted(files_under(wingman)) == sorted([
        ".claude-plugin/icon.svg", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "README.md",
    ])


def test_bundle_carries_copilot_codex_and_cursor_files(exported):
    bundle = exported / "bundles" / "wingman"
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".github/plugin/plugin.json",
                ".cursor-plugin/plugin.json", "rules/stackhawk.mdc", "rules/stackhawk-config.mdc",
                "hooks/cursor/plugin-hooks.json", "hooks/cursor/stop.sh"):
        assert (bundle / rel).is_file(), rel
    names = {re.search(r"^name:\s*(\S+)", p.read_text(), re.M).group(1)
             for p in (bundle / "copilot-skills").glob("*/SKILL.md")}
    assert names == BUNDLED_SKILLS
    assert not (bundle / "skills").exists()


def test_claude_snapshots_equal_the_release_tree(exported, release_tree, claude_catalog):
    """Each Claude snapshot is its release folder, byte for byte and with its modes, minus only
    the files this test allows it to leave out. A lost Claude hook, script or manifest fails."""
    assert sorted(p.name for p in (exported / "plugins").iterdir()) == sorted(claude_catalog)
    for name, source in claude_catalog.items():
        expected = without(files_under(release_tree / source), CLAUDE_SNAPSHOT_OMITS.get(name, ()))
        assert files_under(exported / "plugins" / name) == expected, name


def test_a_lost_claude_file_fails_the_snapshot_comparison(scratch, release_tree):
    """The comparison above is what catches a Claude snapshot that lost a file the layout check
    cannot know about, such as the Claude hooks file."""
    expected = without(files_under(release_tree / "plugins" / "hawkscan"), ())
    assert files_under(scratch / "plugins" / "hawkscan") == expected
    (scratch / "plugins" / "hawkscan" / "hooks" / "hooks.json").unlink()
    assert files_under(scratch / "plugins" / "hawkscan") != expected


def test_bundle_equals_the_release_wingman_folder(exported, release_tree):
    assert files_under(exported / "bundles" / "wingman") == files_under(release_tree / "plugins" / "wingman")


def test_installers_and_the_legacy_rule_list_are_exported(exported, release_tree):
    for name in INSTALLER_FILES:
        assert files_under(exported / "install")[name] == files_under(release_tree / "scripts")[name]
    assert os.access(exported / "install" / "install.sh", os.X_OK)


def test_cursor_catalog_points_at_marketplace_folders(exported, source_repo, claude_catalog):
    with open(exported / ".cursor-plugin" / "marketplace.json") as f:
        catalog = json.load(f)
    with open(source_repo / ".cursor-plugin" / "marketplace.json") as f:
        source = json.load(f)
    assert [e["name"] for e in catalog["plugins"]] == list(claude_catalog)
    for entry, original in zip(catalog["plugins"], source["plugins"]):
        folder = "bundles" if entry["name"] == "wingman" else "plugins"
        assert entry["source"] == f"./{folder}/{entry['name']}"
        assert {k: v for k, v in entry.items() if k != "source"} == {k: v for k, v in original.items() if k != "source"}
    assert {k: v for k, v in catalog.items() if k != "plugins"} == {k: v for k, v in source.items() if k != "plugins"}


def test_every_cursor_manifest_and_skill_carries_the_version(exported):
    manifests = list(exported.glob("*/*/.cursor-plugin/plugin.json"))
    assert len(manifests) == 6
    for path in manifests:
        assert json.loads(path.read_text())["version"] == VERSION, path
    for path in exported.glob("**/SKILL.md"):
        assert re.search(rf"^version: {re.escape(VERSION)}$", path.read_text(), re.M), path


def test_export_is_deterministic(exported, source_repo, tmp_path):
    again = tmp_path / "again"
    run_export(source_repo, again)
    assert files_under(again) == files_under(exported)


def test_manifest_lists_every_file_with_its_hash(exported, source_repo):
    with open(exported / "export-manifest.json") as f:
        manifest = json.load(f)
    commit = git(source_repo, "rev-parse", "HEAD").decode().strip()
    assert manifest["source"]["commit"] == commit
    assert manifest["version"] == VERSION
    files = files_under(exported)
    del files["export-manifest.json"]
    listed = {item["path"]: item for item in manifest["files"]}
    assert sorted(listed) == sorted(files) == [item["path"] for item in manifest["files"]]
    for rel, (executable, data) in files.items():
        assert listed[rel]["sha256"] == hashlib.sha256(data).hexdigest()
        assert listed[rel]["bytes"] == len(data)
        assert listed[rel]["mode"] == ("100755" if executable else "100644")
    text = json.dumps(manifest)
    assert str(exported) not in text and str(source_repo) not in text


def test_export_refuses_a_non_empty_destination(source_repo, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine")
    proc = run_export(source_repo, dest, check=False)
    assert proc.returncode != 0
    assert "not empty" in proc.stderr
    assert sorted(os.listdir(dest)) == ["keep.txt"]


@pytest.mark.parametrize("version", ["v1.2", "1.2", "1.2.3\n", "1.2.3 "])
def test_export_rejects_a_bad_version(source_repo, tmp_path, version):
    proc = run_export(source_repo, tmp_path / "dest", version=version, check=False)
    assert proc.returncode != 0
    assert "is not X.Y.Z" in proc.stderr
    assert not (tmp_path / "dest").exists()


def test_export_rejects_a_symlink_that_leaves_the_tree(source_repo, tmp_path):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    os.symlink("..", clone / "up")
    git(clone, "add", "up")
    git(clone, "commit", "-qm", "a link out of the tree")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert "leaves the tree" in proc.stderr
    assert not (tmp_path / "dest").exists()


def test_export_ignores_the_line_ending_settings_of_the_checkout(source_repo, tmp_path, exported):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    git(clone, "config", "core.autocrlf", "true")
    run_export(clone, tmp_path / "dest")
    assert files_under(tmp_path / "dest") == files_under(exported)


def test_export_folders_have_fixed_modes(exported):
    for dirpath, dirnames, _ in os.walk(exported):
        assert stat.S_IMODE(os.stat(dirpath).st_mode) == 0o755, dirpath


def test_export_reads_the_commit_not_the_working_tree(source_repo, tmp_path):
    rule = source_repo / "plugins" / "hawkscan" / "rules" / "stackhawk.mdc"
    original = rule.read_text()
    try:
        rule.write_text(original + "\nUNCOMMITTED\n")
        run_export(source_repo, tmp_path / "dest")
    finally:
        rule.write_text(original)
    assert "UNCOMMITTED" not in (tmp_path / "dest" / "bundles" / "wingman" / "rules" / "stackhawk.mdc").read_text()


def test_a_failed_export_leaves_no_destination(source_repo, tmp_path):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    (clone / "plugins" / "wingman" / "rules" / "stackhawk.mdc").unlink()
    git(clone, "commit", "-qam", "drop the wingman router copy")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert not (tmp_path / "dest").exists()
    assert not [p for p in os.listdir(tmp_path) if p.startswith(".export-")]


# ─── The layout check: one case per failure class ───

def copy_cursor_files_into_claude_wingman(root, parts):
    for rel in parts:
        source = root / "bundles" / "wingman" / rel
        target = root / "plugins" / "wingman" / rel
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def test_the_layout_the_old_sync_wrote_fails(scratch):
    """The reproduced defect: the old sync kept the Cursor files in the Claude-listed wingman."""
    copy_cursor_files_into_claude_wingman(scratch, (".cursor-plugin", "rules", "hooks"))
    errors = errors_of(scratch)
    assert_error(errors, "Claude Code install of wingman", "2 router rules", "2 stop hooks")


def test_a_stray_router_rule_in_claude_wingman_fails(scratch):
    """No manifest names it: Cursor finds a plugin's rules/ folder by default."""
    copy_cursor_files_into_claude_wingman(scratch, ("rules",))
    assert_error(errors_of(scratch), "Claude Code install of wingman", "2 router rules")


@pytest.mark.parametrize("value", ["True", "true # router", '"true"', "yes", "on", "maybe"])
def test_any_always_apply_that_is_not_false_counts_as_a_router(scratch, value):
    rule = scratch / "plugins" / "wingman" / "rules" / "second.mdc"
    rule.parent.mkdir()
    rule.write_text(f"---\ndescription: StackHawk test\nalwaysApply: {value}\n---\nbody\n")
    assert_error(errors_of(scratch), "Claude Code install of wingman", "2 router rules")


@pytest.mark.parametrize("value", ["false", "False", "no", "false # pointer"])
def test_an_always_apply_that_is_false_is_not_a_router(scratch, value):
    rule = scratch / "plugins" / "wingman" / "rules" / "pointer.mdc"
    rule.parent.mkdir()
    rule.write_text(f"---\ndescription: StackHawk test\nalwaysApply: {value}\n---\nbody\n")
    assert "router rules" not in "\n".join(errors_of(scratch))


def test_a_second_stop_hook_in_claude_wingman_fails(scratch):
    copy_cursor_files_into_claude_wingman(scratch, ("hooks",))
    (scratch / "plugins" / "wingman" / ".cursor-plugin").mkdir()
    (scratch / "plugins" / "wingman" / ".cursor-plugin" / "plugin.json").write_text(
        json.dumps({"name": "wingman", "hooks": "./hooks/cursor/plugin-hooks.json"}))
    assert_error(errors_of(scratch), "Claude Code install of wingman", "2 stop hooks")


def test_a_skills_folder_in_claude_wingman_fails(scratch):
    shutil.copytree(scratch / "bundles" / "wingman" / "copilot-skills", scratch / "plugins" / "wingman" / "skills")
    assert_error(errors_of(scratch), "plugins/wingman", "skills/")


@pytest.mark.parametrize("rel", [
    ".cursor-plugin/marketplace.json",
    "install/install.sh",
    "install/install.ps1",
    "install/cursor-legacy-rules.txt",
    "plugins/hawkscan/.cursor-plugin/plugin.json",
    "bundles/wingman/.cursor-plugin/plugin.json",
])
def test_a_missing_cursor_distribution_file_fails(scratch, rel):
    (scratch / rel).unlink()
    assert_error(errors_of(scratch), rel)


def test_a_bundle_without_its_router_fails(scratch):
    shutil.rmtree(scratch / "bundles" / "wingman" / "rules")
    assert_error(errors_of(scratch), "Cursor install of wingman", "router")


def test_a_bundle_without_its_stop_hook_script_fails(scratch):
    (scratch / "bundles" / "wingman" / "hooks" / "cursor" / "stop.sh").unlink()
    assert_error(errors_of(scratch), "bundles/wingman", "stop.sh")


def test_a_cursor_entry_on_the_claude_wingman_fails(scratch):
    path = scratch / ".cursor-plugin" / "marketplace.json"
    catalog = json.loads(path.read_text())
    for entry in catalog["plugins"]:
        if entry["name"] == "wingman":
            entry["source"] = "./plugins/wingman"
    path.write_text(json.dumps(catalog))
    assert_error(errors_of(scratch), "wingman")


def test_a_lost_claude_hook_script_fails(scratch):
    (scratch / "plugins" / "hawkscan" / "hooks" / "run-hook.cmd").unlink()
    assert_error(errors_of(scratch), "plugins/hawkscan", "run-hook.cmd")


def test_a_wingman_dependency_outside_the_catalog_fails(scratch):
    path = scratch / "plugins" / "wingman" / ".claude-plugin" / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["dependencies"].append("not-a-plugin")
    path.write_text(json.dumps(manifest))
    assert_error(errors_of(scratch), "not-a-plugin")


def test_an_unstamped_cursor_manifest_fails(scratch):
    path = scratch / "plugins" / "hawkscan" / ".cursor-plugin" / "plugin.json"
    manifest = json.loads(path.read_text())
    del manifest["version"]
    path.write_text(json.dumps(manifest))
    assert_error(errors_of(scratch), "plugins/hawkscan/.cursor-plugin/plugin.json", VERSION)
    assert errors_of(scratch, version=None) == []


def test_the_installers_run_against_the_tree(exported):
    assert errors_of(exported, run_installers=True) == []


def test_a_snapshot_the_installers_cannot_use_fails_only_when_they_run(scratch):
    """A curated catalog without hawkscan-ci passes the layout, but install.sh needs that skill."""
    shutil.rmtree(scratch / "plugins" / "hawkscan-ci")
    path = scratch / ".cursor-plugin" / "marketplace.json"
    catalog = json.loads(path.read_text())
    catalog["plugins"] = [e for e in catalog["plugins"] if e["name"] != "hawkscan-ci"]
    path.write_text(json.dumps(catalog))
    assert errors_of(scratch) == []
    assert_error(errors_of(scratch, run_installers=True), "install/install.sh", "hawkscan-ci")


def test_the_check_command_line_reports_and_fails(scratch):
    (scratch / "install" / "install.sh").unlink()
    proc = subprocess.run(["python3", CHECK, "--version", VERSION, str(scratch)], capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert proc.returncode == 1
    assert "install/install.sh" in proc.stderr


def test_the_source_tree_is_checked_with_its_own_catalogs(source_repo):
    """In this repository the Claude catalog lists plugins/wingman with its Cursor files, so the
    check finds the double import that the export removes. Recorded, not fixed here."""
    errors = LAYOUT.check(str(source_repo), version=None, require_installers=False)
    assert_error(errors, "Claude Code install of wingman", "2 router rules")


# ─── Installs from the snapshot layout ───

def run_installer(kind, root, platform, target, home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["HOME"] = str(home)
    if kind == "sh":
        cmd = ["bash", str(root / "install.sh"), "--platform", platform, "--target", str(target)]
    else:
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(root / "install.ps1"),
               "-Platform", platform, "-Target", str(target)]
    return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


def normalized_install(root):
    """Installed files with the SKILL.md version line blanked: a snapshot is stamped, a clone is not."""
    files = {}
    for rel, (executable, data) in files_under(root).items():
        if rel.endswith("SKILL.md"):
            data = re.sub(rb"(?m)^version: .*$", b"version: X", data, count=1)
        files[rel] = (executable, data)
    return files


@pytest.mark.parametrize("kind", INSTALLERS)
def test_snapshot_install_equals_the_clone_install(kind, exported, source_repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    from_snapshot, from_clone = tmp_path / "a", tmp_path / "b"
    from_snapshot.mkdir()
    from_clone.mkdir()
    proc = run_installer(kind, exported / "install", "cursor", from_snapshot, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = run_installer(kind, source_repo / "scripts", "cursor", from_clone, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    snapshot = normalized_install(from_snapshot)
    assert snapshot == normalized_install(from_clone)
    skill = (from_snapshot / ".cursor" / "skills" / "api" / "SKILL.md").read_text()
    assert re.search(rf"^version: {re.escape(VERSION)}$", skill, re.M)
    assert sorted(os.listdir(from_snapshot / ".cursor" / "skills")) == [
        "api", "hawkscan", "hawkscan-ci", "optimize", "stackhawk-data-seed"]


@pytest.mark.parametrize("kind", INSTALLERS)
def test_snapshot_install_removes_legacy_rules(kind, exported, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "p"
    (project / ".cursor" / "rules").mkdir(parents=True)
    (project / ".cursor" / "rules" / "stackhawk-hawkscan.mdc").write_text("---\ndescription: old\n---\n")
    home.mkdir()
    proc = run_installer(kind, exported / "install", "cursor", project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(os.listdir(project / ".cursor" / "rules")) == ["stackhawk-config.mdc", "stackhawk.mdc"]


@pytest.mark.parametrize("kind", INSTALLERS)
def test_snapshot_copilot_install(kind, exported, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "p"
    home.mkdir()
    project.mkdir()
    proc = run_installer(kind, exported / "install", "copilot", project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    skills = project / ".agents" / "skills"
    assert sorted(os.listdir(skills)) == ["hawkscan", "stackhawk-api"]
    assert files_under(skills / "stackhawk-api") == files_under(exported / "plugins" / "stackhawk-api" / "skills" / "api")


@pytest.mark.parametrize("kind", INSTALLERS)
@pytest.mark.parametrize("missing, named", [
    ("plugins/stackhawk-api", "api"),
    ("plugins/hawkscan/rules", "stackhawk.mdc"),
])
def test_an_incomplete_snapshot_stops_the_install_before_any_change(kind, missing, named, scratch, tmp_path):
    shutil.rmtree(scratch / missing)
    home = tmp_path / "home"
    project = tmp_path / "p"
    home.mkdir()
    project.mkdir()
    (project / ".cursor" / "rules").mkdir(parents=True)
    (project / ".cursor" / "rules" / "stackhawk-hawkscan.mdc").write_text("---\ndescription: old\n---\n")
    proc = run_installer(kind, scratch / "install", "cursor", project, home)
    assert proc.returncode != 0
    assert named in proc.stderr
    assert sorted(files_under(project / ".cursor")) == ["rules/stackhawk-hawkscan.mdc"]
