"""The Claude Code hooks of hawkscan do nothing when Cursor runs them, and act as before in Claude Code.

The Cursor app and the Cursor CLI import Claude Code plugins and run their hooks: SessionStart as
sessionStart, PostToolUse as postToolUse, Stop as stop (Cursor 3.9.16, claude-code-types.ts; the
Cursor CLI 2026.11.13 ran the SessionStart hook of an imported plugin in a live headless run). The
router rule and the stop hook of the one native Cursor install do that work in Cursor, so a Claude
hook that acted there would add a second scan reminder, a second context block, and a session
record that says claude-code.

Cursor sets CURSOR_VERSION and CURSOR_PROJECT_DIR for every hook and never CLAUDECODE. Claude Code
2.1.325 sets CLAUDECODE=1 for every hook, also when it inherited a Cursor variable (a live
SessionStart hook in a scratch HOME showed both). plugins/hawkscan/hooks/skip-under-cursor ends a
hook when a Cursor variable is set and CLAUDECODE is not.

Each case runs a command of plugins/hawkscan/hooks/hooks.json as both hosts run it: through a
shell and run-hook.cmd, from a plugin folder with a space in its path, in a git project where the
hook acts (an uncommitted code change, a commit from this minute), with a new HOME. The
environment holds no host variable of the calling shell, then the variables of no host, of
Cursor, of Claude Code, or of both.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN = os.path.join(REPO_ROOT, "plugins", "hawkscan")
GUARD = "skip-under-cursor"
GUARD_LINE = '. "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/skip-under-cursor"'
HOST_PREFIXES = ("CLAUDE", "CURSOR", "HAWK_", "_STACKHAWK", "CODEX_", "GEMINI_")

CURSOR = {"CURSOR_VERSION": "3.9.16", "CURSOR_PROJECT_DIR": "{project}", "CURSOR_PLUGIN_ROOT": "{plugin}"}
CLAUDE = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "claude-session"}
ENVIRONMENTS = {
    "no host": {},
    "Cursor": CURSOR,
    "Cursor project folder only": {"CURSOR_PROJECT_DIR": "{project}"},
    "Claude Code": CLAUDE,
    "Claude Code with a Cursor variable": {**CURSOR, **CLAUDE},
}
SILENT = ("Cursor", "Cursor project folder only")

PAYLOADS = {
    "session-start": {"session_id": "s1", "source": "startup", "hook_event_name": "SessionStart"},
    "post-commit-scan": {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash",
                         "tool_input": {"command": "git commit -m 'feat: add ready'"},
                         "tool_response": {"stdout": "[main 1234567] feat: add ready", "stderr": ""}},
    "skill-activated": {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Skill",
                        "tool_input": {"skill": "hawkscan"}},
    "stop": {"session_id": "s1", "hook_event_name": "Stop", "stop_hook_active": False},
}


def hook_commands():
    """(event, script, command) of every hook in hooks.json."""
    with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
        events = json.load(f)["hooks"]
    found = []
    for event, groups in events.items():
        for group in groups:
            for hook in group["hooks"]:
                parts = hook["command"].replace('"', " ").split()
                found.append((event, parts[1], hook["command"]))
    return found


COMMANDS = hook_commands()
IDS = [f"{event}-{script}" for event, script, _ in COMMANDS]


def git(project, *args):
    subprocess.run(["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


@pytest.fixture
def plugin(tmp_path):
    """The plugin folder as a POSIX checkout has it. .gitattributes leaves the .cmd wrapper to
    core.autocrlf, because cmd.exe runs it on Windows; no POSIX host runs a CRLF copy of it."""
    root = tmp_path / "plugin cache" / "hawkscan"
    shutil.copytree(PLUGIN, root, symlinks=True)
    wrapper = root / "hooks" / "run-hook.cmd"
    wrapper.write_bytes(wrapper.read_bytes().replace(b"\r\n", b"\n"))
    return root


@pytest.fixture
def project(tmp_path):
    """A commit from this minute and an uncommitted change to a code file: every hook acts."""
    path = tmp_path / "project"
    (path / "src").mkdir(parents=True)
    app = path / "src" / "app.py"
    app.write_text("def health():\n    return 'ok'\n")
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "init")
    app.write_text(app.read_text() + "\n\ndef ready():\n    return True\n")
    git(path, "commit", "-qam", "feat: add ready")
    app.write_text(app.read_text() + "\n\ndef live():\n    return True\n")
    return path


def files_of(*roots):
    """path -> bytes of each file, git's objects and index left out (git diff may refresh it)."""
    found = {}
    for root in roots:
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "objects"]
            for name in names:
                full = os.path.join(dirpath, name)
                if name == "index" and os.path.basename(dirpath) == ".git":
                    continue
                with open(full, "rb") as f:
                    found[full] = f.read()
    return found


def same_files(written):
    """The written paths without the HOME folder name and the process id of a session record."""
    return [re.sub(r"/[0-9]+\.json$", "/PID.json", w.split(os.sep, 1)[1]) for w in written]


def run(command, plugin, project, home, variables, stdin):
    env = {k: v for k, v in os.environ.items() if not k.startswith(HOST_PREFIXES)}
    env.update({"HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(plugin), "CLAUDE_PROJECT_DIR": str(project)})
    env.update({k: v.format(project=project, plugin=plugin) for k, v in variables.items()})
    command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin))
    before = files_of(project, home)
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=project, env=env, input=stdin, capture_output=True,
                          text=True, timeout=60, check=False)
    after = files_of(project, home)
    written = sorted(os.path.relpath(p, home.parent) for p in after if before.get(p) != after[p])
    return proc.returncode, proc.stdout.strip(), proc.stderr, written


@pytest.mark.parametrize("event, script, command", COMMANDS, ids=IDS)
def test_each_claude_hook_does_nothing_under_cursor_and_acts_under_claude_code(
        event, script, command, plugin, project, tmp_path):
    outcomes = {}
    for label, variables in ENVIRONMENTS.items():
        home = tmp_path / f"home {label}"
        home.mkdir()
        outcomes[label] = run(command, plugin, project, home, variables, json.dumps(PAYLOADS[script]))
    baseline = outcomes["no host"]
    assert baseline[0] == 0, baseline[2]
    assert baseline[1] or baseline[3], f"{script} did not act in the test project: {baseline}"
    for label in SILENT:
        assert outcomes[label][:2] == (0, ""), (label, outcomes[label])
        assert outcomes[label][3] == [], (label, outcomes[label])
    for label in ("Claude Code", "Claude Code with a Cursor variable"):
        code, stdout, stderr, written = outcomes[label]
        assert code == 0, stderr
        assert stdout == baseline[1], label
        assert same_files(written) == same_files(baseline[3]), label


@pytest.mark.parametrize("script", sorted(PAYLOADS))
def test_the_guard_reads_a_large_payload_before_it_ends_the_hook(script, plugin, project, tmp_path):
    """Cursor writes the payload to stdin. A hook that exits without reading it could make that
    write fail; the guard reads it first."""
    home = tmp_path / "home"
    home.mkdir()
    payload = json.dumps({**PAYLOADS[script], "padding": "x" * 2_000_000})
    code, stdout, stderr, written = run(f'"${{CLAUDE_PLUGIN_ROOT}}/hooks/run-hook.cmd" {script}', plugin, project,
                                        home, CURSOR, payload)
    assert (code, stdout, written) == (0, "", []), stderr


def test_every_hook_runs_through_the_wrapper_and_every_script_sources_the_guard_first():
    """A new hook script must start with the guard, or it acts in Cursor (the layout check, which
    runs each hook as Cursor runs it, fails then too)."""
    scripts = {script for _, script, _ in COMMANDS}
    assert scripts == set(PAYLOADS)
    for _, script, command in COMMANDS:
        assert command.startswith('"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" '), command
    for script in scripts:
        with open(os.path.join(PLUGIN, "hooks", script)) as f:
            lines = [line.rstrip("\n") for line in f]
        code = [line for line in lines if line.strip() and not line.startswith("#")]
        assert code[:2] == ["set -euo pipefail", GUARD_LINE], script
    assert GUARD not in {part for _, _, command in COMMANDS for part in command.replace('"', " ").split()}
