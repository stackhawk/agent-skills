"""The marketplace export: the release payload that stackhawk/agent-skills-marketplace consumes.

`scripts/export-marketplace.py` reads one commit of this repository and writes what the
marketplace publishes from it: a Claude-oriented snapshot of each plugin, the complete wingman
bundle for Copilot, Codex and Cursor, the Cursor catalog, and the Cursor installers.
`scripts/check-marketplace-layout.py` checks such a tree, and the release runs it on the synced
marketplace before the push.

The defect these tests guard: the marketplace once copied all of `plugins/wingman` into the
Claude-listed snapshot. Cursor imports Claude Code plugins, so a Claude Code user with wingman
(and its hawkscan dependency) got the router rule and the stop hook twice. The source had the
same defect: its own Claude catalog listed `plugins/wingman` with the Cursor files. Then the
Cursor files of wingman moved to `cursor-plugins/wingman`, which only the Cursor catalog lists,
and the export builds the marketplace bundle from both folders.

The Claude hawkscan carried the router rule and the stop hook too, so a Claude Code install
next to one native Cursor install still loaded each twice. Now no Claude snapshot carries a
Cursor rule or hook: the Cursor parts of hawkscan live in `cursor-plugins/hawkscan`, which the
export publishes as it is, and the Claude hooks of hawkscan do nothing when Cursor runs them.

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
import sys

import pytest

from tests.git_env import git_env

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(REPO_ROOT, "scripts", "export-marketplace.py")
CHECK = os.path.join(REPO_ROOT, "scripts", "check-marketplace-layout.py")
VERSION = "9.8.7"

# What the Claude-oriented snapshot of a plugin may leave out of its source folder. Owned by
# this test, not by the exporter, so a change that drops more files from a Claude snapshot fails.
CLAUDE_SNAPSHOT_OMITS = {
    "wingman": (".github", "copilot-skills"),
}
CURSOR_PARTS = (".cursor-plugin", "rules", "hooks/cursor")
CURSOR_WINGMAN = "cursor-plugins/wingman"
CURSOR_HAWKSCAN = "cursor-plugins/hawkscan"
INSTALLER_FILES = ("install.sh", "install.ps1", "cursor-legacy-rules.txt")
BUNDLED_SKILLS = {"hawkscan", "stackhawk-api", "stackhawk-data-seed", "stackhawk-optimize"}
INSTALLERS = ["sh"] + (["ps1"] if shutil.which("pwsh") else [])


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAYOUT = load(CHECK, "check_marketplace_layout")

def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], env=git_env(), check=True,
                          capture_output=True).stdout


def snapshot_working_tree(dest):
    """Commit the tracked and new (not ignored) files of this checkout into a fresh repository.
    core.autocrlf=input stores text files with LF, as a commit from this checkout stores them,
    also when the checkout has CRLF line endings (Git for Windows: core.autocrlf=true)."""
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
    git(dest, "config", "core.autocrlf", "input")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "snapshot")


def run_export(source, dest, version=VERSION, ref="HEAD", check=True):
    proc = subprocess.run(
        [sys.executable, EXPORT, "--source-repo", str(source), "--ref", ref, "--version", version,
         "--dest", str(dest)],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
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
    """One error names every needle."""
    assert any(all(needle in error for needle in needles) for error in errors), \
        f"expected one error with {needles!r}, got:\n" + "\n".join(errors)


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
    names = {re.search(r"^name:\s*(\S+)", p.read_text(), re.MULTILINE).group(1)
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


def expected_bundle(release_tree):
    """plugins/wingman as released, with the Cursor parts of cursor-plugins/wingman. The
    bundle keeps one copy of the bundled skills, so its Cursor manifest names copilot-skills/."""
    files = files_under(release_tree / "plugins" / "wingman")
    cursor = files_under(release_tree / CURSOR_WINGMAN)
    for rel, value in cursor.items():
        if any(rel == p or rel.startswith(p + "/") for p in CURSOR_PARTS):
            files[rel] = value
    executable, data = files[".cursor-plugin/plugin.json"]
    manifest = json.loads(data)
    assert manifest["skills"] == "./skills/"
    manifest["skills"] = "./copilot-skills/"
    files[".cursor-plugin/plugin.json"] = (executable, (json.dumps(manifest, indent=2) + "\n").encode())
    return files


def test_bundle_is_the_claude_wingman_with_the_cursor_parts(exported, release_tree):
    assert files_under(exported / "bundles" / "wingman") == expected_bundle(release_tree)


def test_the_cursor_only_skills_equal_the_bundled_copies(release_tree):
    skills = files_under(release_tree / CURSOR_WINGMAN / "skills")
    bundled = files_under(release_tree / "plugins" / "wingman" / "copilot-skills")
    del bundled["README.md"]
    assert skills == bundled and len(skills) > 4


def test_the_exported_bundle_loads_one_router_one_stop_hook_and_the_four_skills(exported):
    layout = LAYOUT.Layout(str(exported))
    bundle = LAYOUT.load_plugin(layout, "bundles/wingman", prefer_cursor=True)
    assert [r.path for r in bundle.rules if r.always] == ["bundles/wingman/rules/stackhawk.mdc"]
    assert [h.path for h in LAYOUT.stop_hooks(bundle)] == ["bundles/wingman/hooks/cursor/plugin-hooks.json"]
    assert LAYOUT.acting_stop_hooks(layout, [bundle]) == ["bundles/wingman/hooks/cursor/plugin-hooks.json"]
    assert {s.name for s in bundle.skills} == BUNDLED_SKILLS
    assert layout.errors == []


def test_the_exported_cursor_hawkscan_is_the_source_folder_without_its_readme(exported, release_tree):
    expected = files_under(release_tree / CURSOR_HAWKSCAN)
    del expected["README.md"]
    assert files_under(exported / CURSOR_HAWKSCAN) == expected
    assert sorted(os.listdir(exported / "cursor-plugins")) == ["hawkscan"]


def test_the_exported_cursor_hawkscan_loads_one_router_one_stop_hook_and_its_skill(exported):
    layout = LAYOUT.Layout(str(exported))
    plugin = LAYOUT.load_plugin(layout, CURSOR_HAWKSCAN, prefer_cursor=True)
    assert [r.path for r in plugin.rules if r.always] == [f"{CURSOR_HAWKSCAN}/rules/stackhawk.mdc"]
    assert LAYOUT.acting_stop_hooks(layout, [plugin]) == [f"{CURSOR_HAWKSCAN}/hooks/cursor/plugin-hooks.json"]
    assert {s.name for s in plugin.skills} == {"hawkscan"}
    assert layout.errors == []


def test_the_claude_hawkscan_carries_no_cursor_file_and_registers_only_silent_hooks(exported):
    """Cursor imports the Claude Code install of hawkscan: no rule, and its Claude hooks (Stop,
    SessionStart, PostToolUse) do nothing when Cursor runs them."""
    hawkscan = exported / "plugins" / "hawkscan"
    for rel in CURSOR_PARTS:
        assert not (hawkscan / rel).exists(), rel
    assert not list(hawkscan.glob("**/*.mdc"))
    layout = LAYOUT.Layout(str(exported))
    plugin = LAYOUT.load_plugin(layout, "plugins/hawkscan", prefer_cursor=True)
    assert plugin.manifest == ".claude-plugin/plugin.json" and plugin.rules == []
    assert {h.event for h in plugin.hooks} == {"sessionStart", "postToolUse", "stop"}
    assert [h for h in plugin.hooks if LAYOUT.hook_acts(layout, plugin, h)] == []
    assert layout.errors == []


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
    folders = {"wingman": "bundles", "hawkscan": "cursor-plugins"}
    for entry, original in zip(catalog["plugins"], source["plugins"]):
        folder = folders.get(entry["name"], "plugins")
        assert entry["source"] == f"./{folder}/{entry['name']}"
        assert {k: v for k, v in entry.items() if k != "source"} == {k: v for k, v in original.items() if k != "source"}
    assert {k: v for k, v in catalog.items() if k != "plugins"} == {k: v for k, v in source.items() if k != "plugins"}


def test_every_cursor_manifest_and_skill_carries_the_version(exported):
    catalog = json.loads((exported / ".cursor-plugin" / "marketplace.json").read_text())
    manifests = list(exported.glob("*/*/.cursor-plugin/plugin.json"))
    assert sorted(p.parent.parent.relative_to(exported).as_posix() for p in manifests) == \
        sorted(e["source"].removeprefix("./") for e in catalog["plugins"])
    for path in manifests:
        assert json.loads(path.read_text())["version"] == VERSION, path
    for path in exported.glob("**/SKILL.md"):
        assert re.search(rf"^version: {re.escape(VERSION)}$", path.read_text(), re.MULTILINE), path


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
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    rule = clone / "cursor-src" / "rules" / "stackhawk.mdc"
    rule.write_text(rule.read_text() + "\nUNCOMMITTED\n")
    run_export(clone, tmp_path / "dest")
    assert "UNCOMMITTED" not in (tmp_path / "dest" / "bundles" / "wingman" / "rules" / "stackhawk.mdc").read_text()


def test_a_failed_export_leaves_no_destination(source_repo, tmp_path):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    (clone / "cursor-plugins" / "wingman" / "rules" / "stackhawk.mdc").unlink()
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
    assert_error(errors, "plugins/wingman/rules: the Claude catalog lists plugins/wingman (wingman)")
    assert_error(errors, "plugins/wingman/hooks/cursor/plugin-hooks.json registers a stop hook that acts")
    assert_error(errors, "Claude Code install of wingman",
                 "+ Cursor catalog install of wingman (bundles/wingman): 2 router rules")
    assert_error(errors, "Claude Code install of wingman", "2 stop hooks act")


def copy_cursor_files_into_claude_hawkscan(root):
    for part in (".cursor-plugin", "rules", "hooks/cursor"):
        source, target = root / CURSOR_HAWKSCAN / part, root / "plugins" / "hawkscan" / part
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def test_the_layout_of_the_previous_release_fails(scratch):
    """The defect of this change: the Claude hawkscan carried the Cursor router and stop hook,
    so a Claude Code install next to one native Cursor install loaded each twice."""
    copy_cursor_files_into_claude_hawkscan(scratch)
    errors = errors_of(scratch)
    assert_error(errors, "plugins/hawkscan/rules: the Claude catalog lists plugins/hawkscan (hawkscan)")
    assert_error(errors, "plugins/hawkscan/.cursor-plugin: the Claude catalog lists plugins/hawkscan")
    assert_error(errors, "Claude Code install of hawkscan (Cursor reads .cursor-plugin/plugin.json when present) "
                 "+ project install: 2 router rules")
    assert_error(errors, "Claude Code install of hawkscan",
                 "+ Cursor catalog install of hawkscan (cursor-plugins/hawkscan): 2 router rules")
    assert_error(errors, "Claude Code install of hawkscan", "2 stop hooks act")


@pytest.mark.parametrize("hook, event", [("stop", "stop"), ("session-start", "sessionStart"),
                                         ("post-commit-scan", "postToolUse"), ("skill-activated", "postToolUse")])
def test_a_claude_hook_that_acts_in_cursor_fails(scratch, hook, event):
    """Without its first line (the Cursor guard), a Claude hook acts when Cursor runs it. The
    probe also runs it with the Claude Code payloads and in the project, so a hook that keys on
    Claude field names or on its working folder cannot look silent."""
    script = scratch / "plugins" / "hawkscan" / "hooks" / hook
    text = script.read_text()
    guard = '. "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/skip-under-cursor"\n'
    assert text.count(guard) == 1
    script.write_text(text.replace(guard, ""))
    errors = errors_of(scratch)
    assert_error(errors, f"plugins/hawkscan/hooks/hooks.json registers a {event} hook that acts when Cursor runs it")
    if event == "stop":
        assert_error(errors, "+ project install: 2 stop hooks act")


def test_a_claude_hook_that_fails_in_cursor_counts_as_acting(scratch):
    """Without the guard file each Claude hook exits with an error; that is not doing nothing."""
    (scratch / "plugins" / "hawkscan" / "hooks" / "skip-under-cursor").unlink()
    assert_error(errors_of(scratch), "plugins/hawkscan/hooks/hooks.json registers a stop hook that acts",
                 "(Cursor run: exit 1)")


@pytest.mark.parametrize("body", ["exit 1\n", "cat > /dev/null\nexit 0\n"], ids=["fails", "silent"])
def test_a_native_stop_hook_that_does_not_work_in_cursor_fails(scratch, body):
    """A failing stop hook counts as acting, so the count alone would pass a broken one as the
    one stop hook of each native install."""
    for folder in ("cursor-plugins/hawkscan", "bundles/wingman"):
        script = scratch / folder / "hooks" / "cursor" / "stop.sh"
        script.write_text("#!/usr/bin/env bash\n" + body)
        assert os.access(script, os.X_OK)
    errors = errors_of(scratch)
    for label in ("Cursor install of hawkscan (cursor-plugins/hawkscan)", "Cursor install of wingman (bundles/wingman)",
                  "project install", "user-level install"):
        assert_error(errors, f"{label}: the stop hook", "does not work when Cursor runs it")


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
    f"{CURSOR_HAWKSCAN}/.cursor-plugin/plugin.json",
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
    assert_error(errors_of(scratch), "missing plugins/wingman/.cursor-plugin/plugin.json", "Cursor catalog entry wingman")


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
    path = scratch / CURSOR_HAWKSCAN / ".cursor-plugin" / "plugin.json"
    manifest = json.loads(path.read_text())
    del manifest["version"]
    path.write_text(json.dumps(manifest))
    assert_error(errors_of(scratch), f"{CURSOR_HAWKSCAN}/.cursor-plugin/plugin.json", VERSION)
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
    proc = subprocess.run([sys.executable, CHECK, "--version", VERSION, str(scratch)], capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
    assert proc.returncode == 1
    assert "install/install.sh" in proc.stderr


def test_the_source_tree_is_checked_with_its_own_catalogs(source_repo):
    """This repository is a Claude Code marketplace too. Its Claude catalog lists plugins/hawkscan
    and plugins/wingman, which carry no Cursor file, and its Cursor catalog lists
    cursor-plugins/hawkscan and cursor-plugins/wingman, so a direct source install never loads
    the router rule or the stop hook twice, also next to one native Cursor install."""
    assert LAYOUT.check(str(source_repo), version=None, require_installers=False) == []


def commit_change(source_repo, tmp_path, change, message):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(source_repo), str(clone))
    change(clone)
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", message)
    return clone


@pytest.mark.parametrize("plugin", ["wingman", "hawkscan"])
@pytest.mark.parametrize("part", [".cursor-plugin", "rules", "hooks/cursor"])
def test_export_refuses_cursor_files_in_the_claude_folder_of_a_cursor_only_plugin(source_repo, tmp_path, part, plugin):
    """Not dropped from the Claude snapshot: refused, so the source cannot carry them either."""
    def change(clone):
        shutil.copytree(clone / "cursor-plugins" / plugin / part, clone / "plugins" / plugin / part)
    clone = commit_change(source_repo, tmp_path, change, f"Cursor files in the Claude {plugin}")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert f"plugins/{plugin}/{part}" in proc.stderr and "must carry no Cursor file" in proc.stderr
    assert not (tmp_path / "dest").exists()


def test_export_refuses_a_cursor_rule_in_a_shared_plugin_folder(source_repo, tmp_path):
    def change(clone):
        shutil.copytree(clone / "cursor-src" / "rules", clone / "plugins" / "api" / "rules")
    clone = commit_change(source_repo, tmp_path, change, "a Cursor rule in the shared api folder")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert "plugins/api/rules" in proc.stderr and "must carry no Cursor rule or hook" in proc.stderr


@pytest.mark.parametrize("rel", [
    f"{CURSOR_WINGMAN}/skills/hawkscan/SKILL.md",
    "plugins/wingman/copilot-skills/stackhawk-api/SKILL.md",
    f"{CURSOR_WINGMAN}/rules/stackhawk.mdc",
    f"{CURSOR_HAWKSCAN}/skills/hawkscan/SKILL.md",
    f"{CURSOR_HAWKSCAN}/hooks/cursor/hooks.json",
])
def test_export_refuses_a_commit_with_stale_generated_files(source_repo, tmp_path, rel):
    """The stamp regenerates the copies, so the payload would be right; the commit is not, and a
    direct install from the source reads it as committed."""
    def change(clone):
        with open(clone / rel, "a") as f:
            f.write("\ndrift\n")
    clone = commit_change(source_repo, tmp_path, change, "a changed generated file")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert "the generated files of the commit differ from what its sources give" in proc.stderr
    assert rel in proc.stderr
    assert not (tmp_path / "dest").exists()


def test_export_refuses_a_cursor_catalog_that_lists_the_claude_wingman(source_repo, tmp_path):
    def change(clone):
        path = clone / ".cursor-plugin" / "marketplace.json"
        catalog = json.loads(path.read_text())
        for entry in catalog["plugins"]:
            if entry["name"] == "wingman":
                entry["source"] = "./plugins/wingman"
        path.write_text(json.dumps(catalog, indent=2) + "\n")
    clone = commit_change(source_repo, tmp_path, change, "the Cursor catalog lists the Claude wingman")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert ".cursor-plugin/marketplace.json" in proc.stdout + proc.stderr


@pytest.mark.parametrize("folder", [CURSOR_WINGMAN, CURSOR_HAWKSCAN])
def test_export_refuses_an_unexpected_file_in_a_cursor_only_folder(source_repo, tmp_path, folder):
    def change(clone):
        (clone / folder / "notes.md").write_text("stray\n")
    clone = commit_change(source_repo, tmp_path, change, "a stray file in the Cursor-only folder")
    proc = run_export(clone, tmp_path / "dest", check=False)
    assert proc.returncode != 0
    assert f"{folder}/notes.md" in proc.stdout + proc.stderr


def test_manifest_maps_each_plugin_to_its_cursor_folder(exported):
    """Format 2: the Cursor parts of hawkscan left plugins/hawkscan. A sync that reads format 1
    refuses the export rather than publish a hawkscan without them."""
    with open(exported / "export-manifest.json") as f:
        manifest = json.load(f)
    assert manifest["format"] == 2
    assert manifest["bundles"] == {"wingman": "plugins/wingman"}
    assert manifest["cursor"] == {
        "hawkscan": CURSOR_HAWKSCAN, "stackhawk-api": "plugins/stackhawk-api", "hawkscan-ci": "plugins/hawkscan-ci",
        "stackhawk-data-seed": "plugins/stackhawk-data-seed", "wingman": "bundles/wingman",
        "stackhawk-optimize": "plugins/stackhawk-optimize"}
    assert "cursor_folders" not in manifest
    published = {i["path"].split("/")[1] for i in manifest["files"] if i["path"].startswith("cursor-plugins/")}
    assert published == {"hawkscan"}


# ─── Verify an export ───

def run_verify(source, root, *args):
    return subprocess.run(
        [sys.executable, EXPORT, "--source-repo", str(source), "--verify", str(root), *args],
        capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
    )


def test_verify_accepts_the_export(exported, source_repo):
    proc = run_verify(source_repo, exported, "--version", VERSION)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "byte for byte" in proc.stdout


def break_unexpected_path(root):
    (root / "notes.txt").write_text("stray\n")
    return "notes.txt: unexpected path"


def break_symlink(root):
    os.symlink("README.md", root / "plugins" / "hawkscan" / "link.md")
    return "plugins/hawkscan/link.md: a symlink"


def break_line_endings(root):
    path = root / "bundles" / "wingman" / "rules" / "stackhawk.mdc"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    return "bundles/wingman/rules/stackhawk.mdc: CRLF line endings"


def break_missing_file(root):
    (root / "bundles" / "wingman" / "hooks" / "cursor" / "stop.sh").unlink()
    return "bundles/wingman/hooks/cursor/stop.sh: missing"


def break_modified_file(root):
    with open(root / "install" / "install.sh", "a") as f:
        f.write("# changed\n")
    return "install/install.sh: modified"


def break_mode(root):
    os.chmod(root / "bundles" / "wingman" / "hooks" / "cursor" / "stop.sh", 0o644)
    return "bundles/wingman/hooks/cursor/stop.sh: mode 100644"


def break_listed_outside_layout(root):
    path = root / "export-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"].append(dict(manifest["files"][0], path="../outside"))
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return "unexpected path '../outside'"


def break_consistent_tamper(root):
    """A changed file whose manifest entry was rewritten to match: only a fresh export shows it."""
    path = root / "bundles" / "wingman" / "rules" / "stackhawk.mdc"
    data = path.read_bytes() + b"\n- extra-skill: never loads.\n"
    path.write_bytes(data)
    manifest_path = root / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["files"]:
        if item["path"] == "bundles/wingman/rules/stackhawk.mdc":
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return "bundles/wingman/rules/stackhawk.mdc: differs from a fresh export"


@pytest.mark.parametrize("damage", [
    break_unexpected_path, break_symlink, break_line_endings, break_missing_file, break_modified_file,
    break_mode, break_listed_outside_layout, break_consistent_tamper,
], ids=lambda f: f.__name__.removeprefix("break_"))
def test_verify_rejects_a_damaged_export(scratch, source_repo, damage):
    needle = damage(scratch)
    proc = run_verify(source_repo, scratch)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert needle in proc.stderr, proc.stderr
    assert "FAILED" in proc.stderr


def test_verify_rejects_an_export_of_another_commit(exported, source_repo, tmp_path):
    clone = commit_change(source_repo, tmp_path, lambda c: (c / "NOTES.md").write_text("later\n"), "a later commit")
    proc = run_verify(clone, exported)
    assert proc.returncode == 1
    commit = git(clone, "rev-parse", "HEAD").decode().strip()
    assert f"HEAD is {commit}" in proc.stderr


def test_verify_rejects_another_version(exported, source_repo):
    proc = run_verify(source_repo, exported, "--version", "9.9.9")
    assert proc.returncode == 1
    assert f"the export is version '{VERSION}'; expected '9.9.9'" in proc.stderr


def test_verify_rejects_a_folder_without_a_manifest(source_repo, tmp_path):
    proc = run_verify(source_repo, tmp_path)
    assert proc.returncode == 1
    assert "cannot read export-manifest.json" in proc.stderr


# ─── Installs from the snapshot layout ───

def run_installer(kind, root, platform, target, home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["HOME"] = str(home)
    if kind == "sh":
        cmd = ["bash", str(root / "install.sh"), "--platform", platform, "--target", str(target)]
    else:
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(root / "install.ps1"),
               "-Platform", platform, "-Target", str(target)]
    return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=False)


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
    assert re.search(rf"^version: {re.escape(VERSION)}$", skill, re.MULTILINE)
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
    (f"{CURSOR_HAWKSCAN}/rules", "stackhawk.mdc"),
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
