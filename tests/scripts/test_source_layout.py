"""The source layout: what a direct install from this repository loads.

This repository is a Claude Code marketplace (`.claude-plugin/marketplace.json`) and a Cursor
marketplace (`.cursor-plugin/marketplace.json`). Released builds come from
stackhawk/agent-skills-marketplace, but a direct install from the source must still be safe.

The defect these tests guard: the Claude catalog listed `plugins/wingman` with the Cursor router
rule, the Cursor stop hook and a Cursor manifest. Claude Code installs wingman's dependencies,
hawkscan among them, and the Cursor app imports Claude Code plugins, so a Claude Code user with
wingman got the router rule and the stop hook twice in Cursor. Now the Claude catalog lists a
`plugins/wingman` with no Cursor file, and only the Cursor catalog lists `cursor-plugins/wingman`.

Each test reads a git snapshot of this working tree, so it sees uncommitted changes the way a
commit carries them.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECK = os.path.join(REPO_ROOT, "scripts", "check-marketplace-layout.py")
CURSOR_WINGMAN = "cursor-plugins/wingman"
INSTALLERS = ["sh"] + (["ps1"] if shutil.which("pwsh") else [])
BUNDLED_SKILLS = {"hawkscan", "stackhawk-api", "stackhawk-data-seed", "stackhawk-optimize"}

# Every Cursor file that a Claude-listed folder may carry. Owned by this test, not by the
# generator: a change that adds a Cursor file to a Claude-listed folder fails here. Only
# hawkscan serves both catalogs with a router rule and a stop hook.
CLAUDE_LISTED_CURSOR_FILES = {
    "plugins/hawkscan": {
        ".cursor-plugin/plugin.json", "rules/stackhawk.mdc", "rules/stackhawk-config.mdc",
        "hooks/cursor/hooks.json", "hooks/cursor/plugin-hooks.json", "hooks/cursor/stop.sh",
    },
    "plugins/api": {".cursor-plugin/plugin.json"},
    "plugins/hawkscan-ci": {".cursor-plugin/plugin.json"},
    "plugins/stackhawk-data-seed": {".cursor-plugin/plugin.json"},
    "plugins/optimize": {".cursor-plugin/plugin.json"},
    "plugins/wingman": set(),
}

# The skills each Claude Code install from the source catalog loads, dependencies included.
CLAUDE_INSTALL_SKILLS = {
    "hawkscan": {"hawkscan"},
    "stackhawk-api": {"api"},
    "hawkscan-ci": {"hawkscan-ci"},
    "stackhawk-data-seed": {"stackhawk-data-seed"},
    "wingman": {"hawkscan", "api", "stackhawk-data-seed", "optimize"},
    "stackhawk-optimize": {"optimize"},
}
HAWKSCAN_CLAUDE_HOOKS = {"SessionStart": 1, "PostToolUse": 2, "Stop": 1}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAYOUT = load(CHECK, "check_marketplace_layout")


def git(path, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", "-C", str(path), *args], env=env, check=True, capture_output=True).stdout


@pytest.fixture(scope="session")
def source(tmp_path_factory):
    """The working tree as a commit carries it: tracked and new files, extracted by git archive."""
    repo = tmp_path_factory.mktemp("repo")
    listed = git(REPO_ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in sorted({p.decode() for p in listed.split(b"\0") if p}):
        src = os.path.join(REPO_ROOT, rel)
        if not os.path.lexists(src):
            continue
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copy2(src, dst)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "snapshot")
    tree = tmp_path_factory.mktemp("source")
    subprocess.run(["tar", "-x", "-C", str(tree)], input=git(repo, "archive", "--format=tar", "HEAD"), check=True)
    return tree


@pytest.fixture
def scratch(source, tmp_path):
    copy = tmp_path / "source"
    shutil.copytree(source, copy, symlinks=True)
    return copy


def catalog(root, rel):
    """catalog name -> folder; the Codex catalog nests the path in a source object."""
    with open(os.path.join(root, rel)) as f:
        entries = json.load(f)["plugins"]
    sources = {e["name"]: e["source"]["path"] if isinstance(e["source"], dict) else e["source"] for e in entries}
    return {name: path.removeprefix("./").rstrip("/") for name, path in sources.items()}


def cursor_files(root, folder):
    """The Cursor files of a folder: its Cursor manifest, every .mdc rule and its Cursor hooks."""
    found = set()
    for dirpath, _, names in os.walk(os.path.join(root, folder)):
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), os.path.join(root, folder)).replace(os.sep, "/")
            if rel.startswith((".cursor-plugin/", "rules/", "hooks/cursor/")) or name.endswith(".mdc"):
                found.add(rel)
    return found


def closure(root, name):
    """The folders of a Claude Code install from the source catalog: the plugin and its dependencies."""
    plugins = catalog(root, ".claude-plugin/marketplace.json")
    with open(os.path.join(root, plugins[name], ".claude-plugin", "plugin.json")) as f:
        dependencies = json.load(f).get("dependencies", [])
    return [plugins[name]] + [plugins[d] for d in dependencies]


def loaded(root, folders, prefer_cursor):
    layout = LAYOUT.Layout(str(root))
    plugins = [LAYOUT.load_plugin(layout, folder, prefer_cursor) for folder in folders]
    routers = [r.path for p in plugins for r in p.rules if r.always]
    hooks = [h.path for p in plugins for h in p.stop_hooks]
    skills = [s.name for p in plugins for s in p.skills]
    assert layout.errors == []
    return routers, hooks, skills


# ─── The source Claude catalog exposes no second router or stop hook ───

def test_the_catalogs_list_the_two_wingman_folders(source):
    assert catalog(source, ".claude-plugin/marketplace.json")["wingman"] == "plugins/wingman"
    assert catalog(source, ".codex-plugin/marketplace.json")["wingman"] == "plugins/wingman"
    assert catalog(source, ".cursor-plugin/marketplace.json")["wingman"] == CURSOR_WINGMAN
    for rel in (".claude-plugin/marketplace.json", ".codex-plugin/marketplace.json"):
        assert not [f for f in catalog(source, rel).values() if f.startswith("cursor-plugins")], rel


def test_claude_listed_folders_carry_only_the_allowed_cursor_files(source):
    plugins = catalog(source, ".claude-plugin/marketplace.json")
    assert sorted(plugins.values()) == sorted(CLAUDE_LISTED_CURSOR_FILES)
    for folder, allowed in CLAUDE_LISTED_CURSOR_FILES.items():
        assert cursor_files(source, folder) == allowed, folder


def test_the_claude_catalog_reaches_one_router_rule_and_one_cursor_stop_script(source):
    plugins = catalog(source, ".claude-plugin/marketplace.json")
    routers, stop_scripts = [], []
    for folder in plugins.values():
        for rel in cursor_files(source, folder):
            full = os.path.join(source, folder, rel)
            if rel.endswith(".mdc"):
                with open(full) as f:
                    fields, _ = LAYOUT.MEASURE.parse_frontmatter(f.read())
                if LAYOUT.always_applied(fields.get("alwaysApply")):
                    routers.append(f"{folder}/{rel}")
            elif rel.endswith("stop.sh"):
                stop_scripts.append(f"{folder}/{rel}")
    assert routers == ["plugins/hawkscan/rules/stackhawk.mdc"]
    assert stop_scripts == ["plugins/hawkscan/hooks/cursor/stop.sh"]


def test_the_layout_check_passes_on_the_source(source):
    assert LAYOUT.check(str(source), require_installers=False) == []


@pytest.mark.parametrize("part", ["rules/stackhawk.mdc", "hooks/cursor/stop.sh", "hooks/cursor/plugin-hooks.json",
                                  ".cursor-plugin/plugin.json", "notes/pointer.mdc"])
def test_a_cursor_file_in_the_claude_wingman_fails_the_layout_check(scratch, part):
    source = scratch / CURSOR_WINGMAN / (part if not part.startswith("notes/") else "rules/stackhawk-config.mdc")
    target = scratch / "plugins" / "wingman" / part
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    errors = LAYOUT.check(str(scratch), require_installers=False)
    assert any(f"plugins/wingman/{part.split('/')[0]}" in e and "must carry no Cursor file" in e for e in errors), errors


@pytest.mark.parametrize("with_claude_manifest", [False, True], ids=["as-is", "with-a-claude-manifest"])
def test_listing_the_cursor_only_wingman_in_the_claude_catalog_fails(scratch, with_claude_manifest):
    path = scratch / ".claude-plugin" / "marketplace.json"
    data = json.loads(path.read_text())
    for entry in data["plugins"]:
        if entry["name"] == "wingman":
            entry["source"] = f"./{CURSOR_WINGMAN}"
    path.write_text(json.dumps(data, indent=2))
    if with_claude_manifest:
        shutil.copytree(scratch / "plugins" / "wingman" / ".claude-plugin", scratch / CURSOR_WINGMAN / ".claude-plugin")
    errors = LAYOUT.check(str(scratch), require_installers=False)
    if with_claude_manifest:
        assert any("Claude Code install of wingman" in e and "2 router rules" in e for e in errors), errors
        assert any("Claude Code install of wingman" in e and "2 stop hooks" in e for e in errors), errors
    else:
        assert any(f"missing {CURSOR_WINGMAN}/.claude-plugin/plugin.json" in e for e in errors), errors


# ─── A direct install from the source loads one router rule and one stop hook ───
# Each channel alone. Combining channels (a Claude Code install that Cursor imports and a
# Cursor catalog install, or either with a project install) loads two of each: the README
# and RELEASING.md tell users to pick one.

@pytest.mark.parametrize("prefer_cursor", [True, False], ids=["cursor-manifest", "claude-manifest"])
def test_a_claude_code_install_of_wingman_from_the_source_loads_one_of_each(source, prefer_cursor):
    """Claude Code installs wingman with its dependencies; the Cursor app imports them all."""
    routers, hooks, skills = loaded(source, closure(source, "wingman"), prefer_cursor)
    assert routers == ["plugins/hawkscan/rules/stackhawk.mdc"]
    assert len(hooks) == 1 and hooks[0].startswith("plugins/hawkscan/hooks/")
    assert sorted(skills) == sorted(CLAUDE_INSTALL_SKILLS["wingman"])


def test_a_cursor_catalog_install_of_wingman_from_the_source_loads_one_of_each(source):
    folder = catalog(source, ".cursor-plugin/marketplace.json")["wingman"]
    routers, hooks, skills = loaded(source, [folder], prefer_cursor=True)
    assert routers == [f"{CURSOR_WINGMAN}/rules/stackhawk.mdc"]
    assert hooks == [f"{CURSOR_WINGMAN}/hooks/cursor/plugin-hooks.json"]
    assert sorted(skills) == sorted(BUNDLED_SKILLS)


@pytest.mark.parametrize("name", sorted(CLAUDE_INSTALL_SKILLS))
def test_every_cursor_catalog_install_from_the_source_loads_at_most_one_of_each(source, name):
    folder = catalog(source, ".cursor-plugin/marketplace.json")[name]
    routers, hooks, skills = loaded(source, [folder], prefer_cursor=True)
    expected = 1 if "hawkscan" in skills else 0
    assert (len(routers), len(hooks)) == (expected, expected), name
    assert len(skills) == len(set(skills)) > 0


# ─── Claude Code installs keep their hooks and skills ───

@pytest.mark.parametrize("name", sorted(CLAUDE_INSTALL_SKILLS))
def test_claude_code_installs_keep_their_skills(source, name):
    layout = LAYOUT.Layout(str(source))
    skills = [s.name for folder in closure(source, name)
              for s in LAYOUT.skills_in(layout, [layout.full(f"{folder}/skills")])]
    assert sorted(skills) == sorted(CLAUDE_INSTALL_SKILLS[name])


@pytest.mark.parametrize("name", ["hawkscan", "wingman"])
def test_claude_code_installs_with_hawkscan_keep_its_claude_hooks(source, name):
    hooks_files = [os.path.join(source, f, "hooks", "hooks.json") for f in closure(source, name)]
    present = [p for p in hooks_files if os.path.isfile(p)]
    assert present == [os.path.join(source, "plugins/hawkscan/hooks/hooks.json")]
    with open(present[0]) as f:
        events = json.load(f)["hooks"]
    assert {event: sum(len(g["hooks"]) for g in groups) for event, groups in events.items()} == HAWKSCAN_CLAUDE_HOOKS
    for groups in events.values():
        for group in groups:
            for hook in group["hooks"]:
                script = hook["command"].split('"')[2].split()[0]
                assert os.access(os.path.join(source, "plugins/hawkscan/hooks", script), os.X_OK), script
    assert os.access(os.path.join(source, "plugins/hawkscan/hooks/run-hook.cmd"), os.X_OK)


def test_the_claude_wingman_has_no_hooks_and_no_skills_folder(source):
    assert sorted(os.listdir(source / "plugins" / "wingman")) == [
        ".claude-plugin", ".codex-plugin", ".github", "README.md", "copilot-skills"]


# ─── Line endings ───

def lf_paths():
    """The generated files (the Cursor adapter and the bundled skill copies), the Cursor hook
    sources they copy, and every Claude hook script but the .cmd wrapper."""
    found = [".cursor-plugin/marketplace.json"]
    for top in ("cursor-plugins", "plugins/wingman/copilot-skills", "plugins/hawkscan/hooks/cursor"):
        for dirpath, _, names in os.walk(os.path.join(REPO_ROOT, top)):
            found += [os.path.relpath(os.path.join(dirpath, n), REPO_ROOT) for n in names]
    for plugin in sorted(os.listdir(os.path.join(REPO_ROOT, "plugins"))):
        base = os.path.join("plugins", plugin)
        if os.path.isfile(os.path.join(REPO_ROOT, base, ".cursor-plugin", "plugin.json")):
            found.append(f"{base}/.cursor-plugin/plugin.json")
        hooks = os.path.join(REPO_ROOT, base, "hooks")
        if os.path.isdir(hooks):
            found += [f"{base}/hooks/{n}" for n in sorted(os.listdir(hooks))
                      if os.path.isfile(os.path.join(hooks, n)) and not n.endswith(".cmd")]
    return sorted(found)


def eol_attributes(paths):
    proc = subprocess.run(["git", "-C", REPO_ROOT, "check-attr", "eol", "--stdin"], input="\n".join(paths),
                          capture_output=True, text=True, check=True)
    return {line.split(": ")[0]: line.split(": ")[2] for line in proc.stdout.splitlines()}


def test_generated_copies_and_hook_scripts_stay_lf_in_every_checkout():
    """generate-cursor-adapter.py --check compares the copies byte for byte with their sources,
    and bash cannot run a CRLF hook script, so .gitattributes forces LF for them."""
    paths = lf_paths()
    assert len(paths) > 50
    assert "plugins/hawkscan/hooks/session-start" in paths and "plugins/api/.cursor-plugin/plugin.json" in paths
    attributes = eol_attributes(paths)
    assert {p: v for p, v in attributes.items() if v != "lf"} == {}
    for rel in paths:
        with open(os.path.join(REPO_ROOT, rel), "rb") as f:
            assert b"\r" not in f.read(), rel


def test_the_cmd_wrapper_keeps_the_line_endings_of_the_checkout():
    """cmd.exe can misread a batch file with LF line endings."""
    assert eol_attributes(["plugins/hawkscan/hooks/run-hook.cmd"]) == {"plugins/hawkscan/hooks/run-hook.cmd": "unspecified"}


# ─── The installers resolve the split layout ───

def run_installer(kind, root, target, home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["HOME"] = str(home)
    if kind == "sh":
        cmd = ["bash", str(root / "scripts" / "install.sh"), "--platform", "cursor", "--target", str(target)]
    else:
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(root / "scripts" / "install.ps1"),
               "-Platform", "cursor", "-Target", str(target)]
    return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
                          check=False)


def installed(project):
    files = {}
    for dirpath, _, names in os.walk(project / ".cursor"):
        for name in names:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                files[os.path.relpath(full, project / ".cursor")] = (os.access(full, os.X_OK), f.read())
    return files


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.mark.parametrize("kind", INSTALLERS)
def test_a_source_project_install_has_one_router_rule_and_one_stop_entry(kind, source, home, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    proc = run_installer(kind, source, project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rules = sorted(os.listdir(project / ".cursor" / "rules"))
    assert rules == ["stackhawk-config.mdc", "stackhawk.mdc"]
    routers = []
    for name in rules:
        fields, _ = LAYOUT.MEASURE.parse_frontmatter((project / ".cursor" / "rules" / name).read_text())
        if LAYOUT.always_applied(fields.get("alwaysApply")):
            routers.append(name)
    assert routers == ["stackhawk.mdc"]
    stops = json.loads((project / ".cursor" / "hooks.json").read_text())["hooks"]["stop"]
    assert stops == [{"command": ".cursor/hooks/stackhawk-stop.sh", "loop_limit": 1}]
    names = {re.search(r"^name:\s*(\S+)", (p / "SKILL.md").read_text(), re.MULTILINE).group(1)
             for p in (project / ".cursor" / "skills").iterdir()}
    assert names == {"hawkscan", "api", "hawkscan-ci", "stackhawk-data-seed", "optimize"}


@pytest.mark.parametrize("kind", INSTALLERS)
def test_the_installers_never_read_the_cursor_only_folder(kind, source, scratch, home, tmp_path):
    """They copy the canonical skills, rules and hook of plugins/: a changed or missing
    cursor-plugins/ changes nothing in the install."""
    expected_project, project = tmp_path / "expected", tmp_path / "project"
    expected_project.mkdir()
    project.mkdir()
    proc = run_installer(kind, source, expected_project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for rel in ("skills/hawkscan/SKILL.md", "rules/stackhawk.mdc", "hooks/cursor/stop.sh"):
        with open(scratch / CURSOR_WINGMAN / rel, "a") as f:
            f.write("\nchanged\n")
    proc = run_installer(kind, scratch, project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert installed(project) == installed(expected_project)
    shutil.rmtree(scratch / "cursor-plugins")
    shutil.rmtree(project / ".cursor")
    proc = run_installer(kind, scratch, project, home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert installed(project) == installed(expected_project)


@pytest.mark.parametrize("kind", INSTALLERS)
def test_a_source_install_without_the_hawkscan_rules_stops_before_any_change(kind, scratch, home, tmp_path):
    """The router lives in plugins/hawkscan/rules/; the installers never fall back to a copy."""
    shutil.rmtree(scratch / "plugins" / "hawkscan" / "rules")
    project = tmp_path / "project"
    project.mkdir()
    proc = run_installer(kind, scratch, project, home)
    assert proc.returncode != 0
    assert "stackhawk.mdc" in proc.stderr
    assert not (project / ".cursor").exists()
