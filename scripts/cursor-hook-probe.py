#!/usr/bin/env python3
"""Run one plugin hook as Cursor runs it, and tell whether it acts.

The Cursor app and the Cursor CLI import Claude Code plugins and run their hooks: SessionStart
as sessionStart, PostToolUse as postToolUse (the matcher Bash as Shell), Stop as stop, and the
other mapped events. scripts/check-marketplace-layout.py uses this module to tell the hooks
that act in Cursor from the ones that do nothing there.

A run gives the hook what Cursor gives it. The sources are the code of the Cursor app 3.9.16
(_buildHookEnvironment and _getHookCwd in workbench.desktop.main.js; the Claude event map in
claude-code-types.ts) and live runs of the Cursor CLI 2026.11.13, which set the same variables:
  - the command, with the plugin folder in place of ${CURSOR_PLUGIN_ROOT} and
    ${CLAUDE_PLUGIN_ROOT}, run by /bin/sh;
  - the environment: CURSOR_PROJECT_DIR, CURSOR_VERSION, CLAUDE_PROJECT_DIR,
    CURSOR_PLUGIN_ROOT and CLAUDE_PLUGIN_ROOT, plus PATH, LANG and TMPDIR. Never CLAUDECODE:
    Claude Code sets it for its own hooks, and Cursor does not;
  - the working folder: the project for stop and subagentStop, else the plugin folder;
  - on stdin, a JSON payload with the common fields and those of the event.
The project is a new git repository with one commit and an uncommitted change to its tracked
code file, so a stop hook that asks for a scan when code changed asks. HOME is a new empty
folder. The hook acts when it prints to stdout, writes a file in the project or in HOME, or
exits with an error: a hook that does nothing in Cursor exits 0, silent.

Usage, to probe one hook by hand:
  cursor-hook-probe.py PLUGIN_DIR EVENT COMMAND
"""
import collections
import json
import os
import subprocess
import sys
import tempfile

CURSOR_VERSION = "0.0.0-hook-probe"
PROJECT_EVENTS = ("stop", "subagentStop")  # Cursor runs a plugin's hooks for these in the project
TIMEOUT_SECONDS = 60

Result = collections.namedtuple("Result", "acts exit stdout written")


def make_project(root):
    """A git project with one commit, and an uncommitted change to its code file."""
    project = os.path.join(root, "project")
    os.makedirs(os.path.join(project, "src"))
    app = os.path.join(project, "src", "app.py")
    with open(app, "w", encoding="utf-8") as f:
        f.write("def health():\n    return 'ok'\n")
    git = ["git", "-C", project, "-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
           "-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(git + args, check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    with open(app, "a", encoding="utf-8") as f:
        f.write("\n\ndef ready():\n    return True\n")
    return project


def payload(event, project):
    data = {"conversation_id": "hook-probe", "generation_id": "hook-probe", "model": "hook-probe",
            "hook_event_name": event, "cursor_version": CURSOR_VERSION, "workspace_roots": [project],
            "user_email": None, "transcript_path": None}
    if event == "stop":
        data.update({"status": "completed", "loop_count": 0})
    elif event == "postToolUse":
        data.update({"tool_name": "Shell", "tool_input": {"command": "git commit -m 'feat: add health'"},
                     "tool_output": "[main 1234567] feat: add health", "duration_ms": 1})
    elif event == "sessionStart":
        data.update({"session_id": "hook-probe", "is_background_agent": False, "composer_mode": "agent"})
    return json.dumps(data)


def files_of(*roots):
    """path -> bytes of every file under the roots; git's objects and index (git diff may
    refresh it) left out."""
    found = {}
    for root in roots:
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "objects"]
            for name in names:
                if name == "index" and os.path.basename(dirpath) == ".git":
                    continue
                full = os.path.join(dirpath, name)
                with open(full, "rb") as f:
                    found[full] = f.read()
    return found


def probe(plugin_dir, event, command):
    """Run the command of one hook of the plugin folder as Cursor runs it for the event.
    Raises OSError or subprocess.SubprocessError when the hook cannot run at all."""
    plugin_dir = os.path.abspath(plugin_dir)
    with tempfile.TemporaryDirectory(prefix="cursor-hook-probe-") as scratch:
        project = make_project(scratch)
        home = os.path.join(scratch, "home")
        os.makedirs(home)
        command = command.replace("${CURSOR_PLUGIN_ROOT}", plugin_dir).replace("${CLAUDE_PLUGIN_ROOT}", plugin_dir)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8",
            "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()), "HOME": home,
            "CURSOR_PROJECT_DIR": project, "CURSOR_VERSION": CURSOR_VERSION, "CLAUDE_PROJECT_DIR": project,
            "CURSOR_PLUGIN_ROOT": plugin_dir, "CLAUDE_PLUGIN_ROOT": plugin_dir,
        }
        cwd = project if event in PROJECT_EVENTS else plugin_dir
        before = files_of(project, home)
        proc = subprocess.run(["/bin/sh", "-c", command], cwd=cwd, env=env, input=payload(event, project),
                              capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
        after = files_of(project, home)
        written = sorted(os.path.relpath(path, scratch) for path in after if before.get(path) != after[path])
        stdout = proc.stdout.strip()
        return Result(bool(stdout) or bool(written) or proc.returncode != 0, proc.returncode, stdout, written)


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    result = probe(*sys.argv[1:])
    print(json.dumps(result._asdict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
