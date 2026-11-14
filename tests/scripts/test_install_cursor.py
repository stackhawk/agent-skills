"""The Cursor installers install skills, two rules and one merged hook entry, and nothing else.

`scripts/install.sh --platform cursor` (and `install.ps1 -Platform cursor`) once copied 28
generated rules next to the five skills, so every rule body was a second copy of a skill
file and the always-applied rule put about 30 KB into every chat. They also replaced the
whole `.cursor/hooks.json`, deleting the user's own hooks, and at user level wrote a hook
command that does not resolve from `~/.cursor/`, where Cursor runs user hooks.

Each case runs the real installer against a throwaway project and a fake HOME. The pwsh
cases run install.ps1 with PowerShell 7 when it is installed (PowerShell 5.1 is not
covered here). Both installers must give the same result.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALL_SH = os.path.join(REPO_ROOT, "scripts", "install.sh")
INSTALL_PS1 = os.path.join(REPO_ROOT, "scripts", "install.ps1")
MEASURE = os.path.join(REPO_ROOT, "scripts", "measure-cursor-context.py")
LEGACY_RULES_DIR = os.path.join(REPO_ROOT, "cursor", ".cursor", "rules")
SKILLS = {
    "hawkscan": "plugins/hawkscan/skills/hawkscan",
    "api": "plugins/api/skills/api",
    "hawkscan-ci": "plugins/hawkscan-ci/skills/hawkscan-ci",
    "stackhawk-data-seed": "plugins/stackhawk-data-seed/skills/stackhawk-data-seed",
    "optimize": "plugins/optimize/skills/optimize",
}
RULES = ["stackhawk-config.mdc", "stackhawk.mdc"]
PROJECT_ENTRY = {"command": ".cursor/hooks/stackhawk-stop.sh", "loop_limit": 1}
USER_ENTRY = {"command": "./hooks/stackhawk-stop.sh", "loop_limit": 1}
LEGACY_STOP_MARKER = "# Cursor stop hook for hawkscan plugin"

# Tools install.sh shells out to; a PATH holding only these has no python3.
NO_PYTHON_TOOLS = ["bash", "cp", "mkdir", "rm", "ls", "grep", "sed", "cat", "chmod", "dirname", "tr", "head", "mv", "env"]

INSTALLERS = ["sh"] + (["ps1"] if shutil.which("pwsh") else [])


def git(path, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def project(home):
    project = home / "work" / "proj"
    (project / "src").mkdir(parents=True)
    (project / ".github" / "workflows").mkdir(parents=True)
    (project / "src" / "app.py").write_text("def health():\n    return 'ok'\n")
    (project / ".github" / "workflows" / "ci.yml").write_text("on: [push]\n")
    git(project, "init", "-q", "-b", "main")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "init")
    return project


def install(kind, target, home, path=None, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["HOME"] = str(home)
    if path:
        env["PATH"] = path
    if kind == "sh":
        cmd = ["bash", INSTALL_SH, "--platform", "cursor", "--target", str(target)]
    else:
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", INSTALL_PS1, "-Platform", "cursor", "-Target", str(target)]
    proc = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
                          check=False)
    if check:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def files_under(root):
    out = set()
    for dirpath, _dirs, filenames in os.walk(root):
        for name in filenames:
            out.add(os.path.relpath(os.path.join(dirpath, name), root))
    return out


def expected_skill_files(prefix="skills"):
    out = set()
    for name, src in SKILLS.items():
        for rel in files_under(os.path.join(REPO_ROOT, src)):
            out.add(os.path.join(prefix, name, rel))
    return out


def hooks(dot_cursor):
    with open(dot_cursor / "hooks.json") as f:
        return json.load(f)


# A rule that an older release generated and today's generator no longer writes.
OLD_RELEASE_RULE = "stackhawk-api-hawkop.mdc"


def write_legacy_install(dot_cursor):
    """The rules and hook the old installer left: today's 28 rules, one rule from an
    older release, and a stop.sh hook with its hooks.json entry."""
    rules = dot_cursor / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    for name in os.listdir(LEGACY_RULES_DIR):
        shutil.copy(os.path.join(LEGACY_RULES_DIR, name), rules / name)
    (rules / OLD_RELEASE_RULE).write_text("---\nalwaysApply: false\n---\nhawkop\n")
    (dot_cursor / "hooks").mkdir(exist_ok=True)
    (dot_cursor / "hooks" / "stop.sh").write_text(f"#!/usr/bin/env bash\n{LEGACY_STOP_MARKER}\nexit 0\n")
    (dot_cursor / "hooks.json").write_text(json.dumps(
        {"version": 1, "hooks": {"stop": [{"command": ".cursor/hooks/stop.sh"}]}}, indent=2))


def stop_payload():
    return json.dumps({"conversation_id": "c", "status": "completed", "loop_count": 0, "workspace_roots": []})


def run_hook_command(command, cwd, project_dir):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
    env["CURSOR_PROJECT_DIR"] = str(project_dir)
    script = f"{command} <<'CURSOR_HOOK_EOF'\n{stop_payload()}\nCURSOR_HOOK_EOF"
    proc = subprocess.run(["sh", "-c", script], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30,
                          check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


# ---------------------------------------------------------------- project installs


@pytest.mark.parametrize("kind", INSTALLERS)
def test_project_install_writes_exactly_the_new_layout(kind, project, home):
    install(kind, project, home)
    dot_cursor = project / ".cursor"
    expected = expected_skill_files() | {f"rules/{r}" for r in RULES} | {"hooks.json", "hooks/stackhawk-stop.sh"}
    assert files_under(dot_cursor) == expected
    for rule in RULES:
        with open(os.path.join(REPO_ROOT, "cursor-src", "rules", rule), "rb") as source:
            assert (dot_cursor / "rules" / rule).read_bytes() == source.read()
    assert hooks(dot_cursor) == {"version": 1, "hooks": {"stop": [PROJECT_ENTRY]}}
    assert os.access(dot_cursor / "hooks" / "stackhawk-stop.sh", os.X_OK)


@pytest.mark.parametrize("kind", INSTALLERS)
def test_project_install_meets_the_context_budgets(kind, project, home):
    install(kind, project, home)
    proc = subprocess.run([sys.executable, MEASURE, "--check", "--json", str(project / ".cursor")],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["rules"] == {"always": 1, "glob": 1, "agent-requested": 0, "manual": 0}
    assert report["skills"] == 5
    # The adapter itself (everything outside skills/) stays small; skill growth is not gated here.
    adapter = [f for f in files_under(project / ".cursor") if not f.startswith("skills/")]
    assert len(adapter) == 4
    assert sum(os.path.getsize(project / ".cursor" / f) for f in adapter) < 8000


def test_installed_skill_links_resolve(project, home):
    install("sh", project, home)
    skills = project / ".cursor" / "skills"
    broken = []
    for rel in files_under(skills):
        if not rel.endswith(".md"):
            continue
        full = skills / rel
        for target in re.findall(r"\]\(([^)\s]+)\)", full.read_text()):
            if re.match(r"^(?:[a-z]+:|#|/)", target):
                continue
            if not (full.parent / target.split("#")[0]).exists():
                broken.append(f"{rel} -> {target}")
    assert not broken, broken


@pytest.mark.parametrize("kind", INSTALLERS)
def test_existing_hooks_are_kept_and_reinstall_is_idempotent(kind, project, home):
    dot_cursor = project / ".cursor"
    dot_cursor.mkdir()
    mine = {"version": 1, "hooks": {
        "sessionStart": [{"command": "./my-session.sh"}],
        "stop": [{"command": ".cursor/hooks/my-own-stop.sh", "timeout": 5}],
    }}
    (dot_cursor / "hooks.json").write_text(json.dumps(mine, indent=2))
    install(kind, project, home)
    install(kind, project, home)
    merged = hooks(dot_cursor)
    assert merged["hooks"]["sessionStart"] == mine["hooks"]["sessionStart"]
    assert merged["hooks"]["stop"] == mine["hooks"]["stop"] + [PROJECT_ENTRY]
    assert merged["version"] == 1


@pytest.mark.parametrize("kind", INSTALLERS)
def test_upgrade_removes_the_legacy_install_only(kind, project, home):
    dot_cursor = project / ".cursor"
    write_legacy_install(dot_cursor)
    (dot_cursor / "rules" / "my-team.mdc").write_text("---\nalwaysApply: false\n---\nmine\n")
    (dot_cursor / "rules" / "stackhawk-custom.mdc").write_text("---\nalwaysApply: false\n---\nmine\n")
    proc = install(kind, project, home)
    assert sorted(os.listdir(dot_cursor / "rules")) == sorted(RULES + ["my-team.mdc", "stackhawk-custom.mdc"])
    assert not (dot_cursor / "hooks" / "stop.sh").exists()
    assert hooks(dot_cursor)["hooks"]["stop"] == [PROJECT_ENTRY]
    assert "deprecated" in (proc.stdout + proc.stderr).lower()
    assert "Removed 29 legacy" in proc.stdout + proc.stderr


@pytest.mark.parametrize("kind", INSTALLERS)
def test_a_foreign_stop_sh_is_left_alone(kind, project, home):
    dot_cursor = project / ".cursor"
    (dot_cursor / "hooks").mkdir(parents=True)
    (dot_cursor / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\necho mine\n")
    (dot_cursor / "hooks.json").write_text(json.dumps({"version": 1, "hooks": {"stop": [{"command": ".cursor/hooks/stop.sh"}]}}))
    install(kind, project, home)
    assert (dot_cursor / "hooks" / "stop.sh").read_text() == "#!/usr/bin/env bash\necho mine\n"
    assert hooks(dot_cursor)["hooks"]["stop"] == [{"command": ".cursor/hooks/stop.sh"}, PROJECT_ENTRY]


@pytest.mark.parametrize("kind", INSTALLERS)
def test_invalid_hooks_json_stops_the_install_before_any_change(kind, project, home):
    dot_cursor = project / ".cursor"
    dot_cursor.mkdir()
    (dot_cursor / "hooks.json").write_text("{not json")
    proc = install(kind, project, home, check=False)
    assert proc.returncode != 0
    assert "hooks.json" in proc.stdout + proc.stderr
    assert (dot_cursor / "hooks.json").read_text() == "{not json"
    assert files_under(dot_cursor) == {"hooks.json"}


@pytest.mark.parametrize("kind", INSTALLERS)
@pytest.mark.parametrize("rule", RULES)
def test_a_users_own_rule_with_our_name_is_not_replaced(kind, rule, project, home):
    rules = project / ".cursor" / "rules"
    rules.mkdir(parents=True)
    mine = "---\ndescription: Our team policy for StackHawk findings.\nalwaysApply: true\n---\nOur rules.\n"
    (rules / rule).write_text(mine)
    proc = install(kind, project, home, check=False)
    assert proc.returncode != 0
    assert rule in proc.stdout + proc.stderr
    assert (rules / rule).read_text() == mine
    assert files_under(project / ".cursor") == {f"rules/{rule}"}


@pytest.mark.parametrize("kind", INSTALLERS)
def test_a_foreign_skill_folder_is_not_replaced(kind, project, home):
    foreign = project / ".cursor" / "skills" / "api"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("---\nname: api\ndescription: Another vendor's API helper.\n---\nbody\n")
    proc = install(kind, project, home, check=False)
    assert proc.returncode != 0
    assert "api" in proc.stdout + proc.stderr
    assert files_under(project / ".cursor") == {"skills/api/SKILL.md"}


def test_without_python_a_new_hooks_file_is_still_written(project, home, tmp_path):
    bindir = tmp_path / "nopython-bin"
    bindir.mkdir()
    for tool in NO_PYTHON_TOOLS:
        os.symlink(shutil.which(tool), bindir / tool)
    install("sh", project, home, path=str(bindir))
    assert hooks(project / ".cursor") == {"version": 1, "hooks": {"stop": [PROJECT_ENTRY]}}


def test_without_python_an_existing_hooks_file_is_left_alone(project, home, tmp_path):
    bindir = tmp_path / "nopython-bin"
    bindir.mkdir()
    for tool in NO_PYTHON_TOOLS:
        os.symlink(shutil.which(tool), bindir / tool)
    dot_cursor = project / ".cursor"
    dot_cursor.mkdir()
    original = json.dumps({"version": 1, "hooks": {"sessionStart": [{"command": "./x.sh"}]}})
    (dot_cursor / "hooks.json").write_text(original)
    proc = install("sh", project, home, path=str(bindir))
    assert (dot_cursor / "hooks.json").read_text() == original
    assert ".cursor/hooks/stackhawk-stop.sh" in proc.stdout + proc.stderr
    assert (dot_cursor / "hooks" / "stackhawk-stop.sh").exists()


def test_project_hook_command_runs_from_the_project_root(project, home):
    install("sh", project, home)
    with open(project / "src" / "app.py", "a") as f:
        f.write("# edit\n")
    out = run_hook_command(hooks(project / ".cursor")["hooks"]["stop"][0]["command"], project, project)
    assert "followup_message" in json.loads(out)


# ---------------------------------------------------------------- user-level installs


@pytest.mark.parametrize("kind", INSTALLERS)
def test_user_level_install(kind, project, home):
    dot_cursor = home / ".cursor"
    write_legacy_install(dot_cursor)
    data = hooks(dot_cursor)
    data["hooks"]["sessionStart"] = [{"command": "./hooks/captain-session.sh"}]
    (dot_cursor / "hooks.json").write_text(json.dumps(data))
    install(kind, home, home)
    assert expected_skill_files() <= files_under(dot_cursor)
    assert os.listdir(dot_cursor / "rules") == [], "user level installs no rules and removes the legacy ones"
    merged = hooks(dot_cursor)
    assert merged["hooks"]["sessionStart"] == [{"command": "./hooks/captain-session.sh"}]
    assert merged["hooks"]["stop"] == [USER_ENTRY]
    assert not (dot_cursor / "hooks" / "stop.sh").exists()
    # Cursor runs user hooks from ~/.cursor/ and gives the project in CURSOR_PROJECT_DIR.
    with open(project / "src" / "app.py", "a") as f:
        f.write("# edit\n")
    out = run_hook_command(USER_ENTRY["command"], dot_cursor, project)
    assert "followup_message" in json.loads(out)


@pytest.mark.parametrize("kind", INSTALLERS)
@pytest.mark.parametrize("link", ["target", "home-parent"])
def test_user_level_is_detected_through_symlinks(kind, link, tmp_path):
    real_home = tmp_path / "real" / "home"
    real_home.mkdir(parents=True)
    if link == "target":
        # The target is a link to the home directory.
        home, target = real_home, tmp_path / "home-link"
        os.symlink(real_home, target)
    else:
        # HOME is reached through a linked parent folder (like /tmp -> /private/tmp).
        os.symlink(tmp_path / "real", tmp_path / "linked")
        home, target = tmp_path / "linked" / "home", real_home
    install(kind, target, home)
    assert hooks(real_home / ".cursor")["hooks"]["stop"] == [USER_ENTRY]
    assert not (real_home / ".cursor" / "rules").exists()


@pytest.mark.skipif("ps1" not in INSTALLERS or not os.path.islink("/tmp"),
                    reason="needs pwsh and a /tmp link at the filesystem root (macOS)")
@pytest.mark.parametrize("level", ["project", "user"])
def test_ps1_follows_a_link_directly_under_the_root(level):
    """macOS /tmp is a relative link at the root (/tmp -> private/tmp), and so is /var, where
    temporary folders live. Split-Path -Parent gives "" for /tmp, which once failed every install
    through such a path."""
    import tempfile
    with tempfile.TemporaryDirectory(dir="/tmp") as scratch:
        home = os.path.join(scratch, "home")
        project = os.path.join(home, "proj")
        os.makedirs(project)
        target = home if level == "user" else project
        out = install("ps1", target, home).stdout
        assert f"({level} level)" in out
        assert os.path.isfile(os.path.join(target, ".cursor", "hooks", "stackhawk-stop.sh"))


@pytest.mark.skipif("ps1" not in INSTALLERS, reason="pwsh not installed")
def test_both_installers_give_the_same_project_install(tmp_path, home):
    results = {}
    for kind in ("sh", "ps1"):
        proj = tmp_path / kind
        proj.mkdir()
        (proj / ".cursor").mkdir()
        (proj / ".cursor" / "hooks.json").write_text(json.dumps({"version": 1, "hooks": {"afterFileEdit": [{"command": "./a.sh"}]}}))
        install(kind, proj, home)
        tree = {rel: (proj / ".cursor" / rel).read_bytes() for rel in files_under(proj / ".cursor") if rel != "hooks.json"}
        results[kind] = (tree, hooks(proj / ".cursor"))
    assert results["sh"] == results["ps1"]
