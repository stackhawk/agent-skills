#!/usr/bin/env python3
"""Run one plugin hook as Cursor runs it, and tell whether it acts.

The Cursor app and the Cursor CLI import Claude Code plugins and run their hooks: SessionStart
as sessionStart, PostToolUse as postToolUse (the matcher Bash as Shell), Stop as stop, and the
other mapped events. scripts/check-marketplace-layout.py uses this module to tell the hooks
that act in Cursor from the ones that do nothing there.

The Cursor run gives the hook what Cursor gives it, from a copy of the plugin folder as a POSIX
checkout has it (see posix_copy). The sources are the code of the Cursor app 3.9.16
(_buildHookEnvironment and _getHookCwd in workbench.desktop.main.js; the Claude event map in
claude-code-types.ts) and live runs of the Cursor CLI 2026.11.13, which set the same variables:
  - the command, with the copy of the plugin folder in place of ${CURSOR_PLUGIN_ROOT} and
    ${CLAUDE_PLUGIN_ROOT}, run by /bin/sh;
  - the environment: CURSOR_PROJECT_DIR, CURSOR_VERSION, CLAUDE_PROJECT_DIR,
    CURSOR_PLUGIN_ROOT and CLAUDE_PLUGIN_ROOT, plus PATH, LANG and TMPDIR. Not CLAUDECODE:
    Claude Code sets it for its own hooks, and Cursor does not;
  - the working folder: the project for stop and subagentStop, else the plugin folder;
  - on stdin, a JSON payload with the common fields (cursor_version among them) and those of
    the event.
The probe also runs the hook in other variants (see variants): with an inherited CLAUDECODE=1,
as when Cursor starts from a Claude Code shell; with the Claude Code payloads of the event; and
in the project, for an event that Cursor runs in the plugin folder. Each run gets a new git
project, with a commit from this minute and an uncommitted change to its tracked code file, and
a new empty HOME. So a stop hook that asks for a scan when code changed asks, and a hook that
reports a new commit reports. A run acts when the hook prints to stdout, writes a file in the
project or in HOME, or exits with an error: a hook that does nothing in Cursor exits 0, silent.
A hook acts when any run acts.

Usage, to probe one hook by hand:
  cursor-hook-probe.py PLUGIN_DIR EVENT COMMAND
"""
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

CURSOR_VERSION = "0.0.0-hook-probe"
PROJECT_EVENTS = ("stop", "subagentStop")  # Cursor runs a plugin's hooks for these in the project
TIMEOUT_SECONDS = 60
# The Claude Code payloads of the events that Cursor maps from Claude Code events. The probe
# sends them too, so that a hook that keys on Claude field names cannot look silent only because
# Cursor names its fields differently.
CLAUDE_PAYLOADS = {
    "sessionStart": [("Claude SessionStart payload", {"hook_event_name": "SessionStart", "source": "startup"})],
    "postToolUse": [
        ("Claude Bash payload", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "git commit -m 'feat: add health'"},
                                 "tool_response": {"stdout": "[main 1234567] feat: add health", "stderr": ""}}),
        ("Claude Skill payload", {"hook_event_name": "PostToolUse", "tool_name": "Skill",
                                  "tool_input": {"skill": "hawkscan"}}),
    ],
    "stop": [("Claude Stop payload", {"hook_event_name": "Stop", "stop_hook_active": False})],
}

Result = collections.namedtuple("Result", "acts exit stdout written variant")
_cache = {}


def make_project(root):
    """A git project with a commit from this minute, and an uncommitted change to its code file."""
    project = os.path.join(root, "project")
    os.makedirs(os.path.join(project, "src"))
    app = os.path.join(project, "src", "app.py")
    git = ["git", "-C", project, "-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
           "-c", "commit.gpgsign=false"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    with open(app, "w", encoding="utf-8") as f:
        f.write("def health():\n    return 'ok'\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(git + args, check=True, capture_output=True, env=env, timeout=TIMEOUT_SECONDS)
    with open(app, "a", encoding="utf-8") as f:
        f.write("\n\ndef ready():\n    return True\n")
    subprocess.run(git + ["commit", "-qam", "feat: add health"], check=True, capture_output=True,
                   env=env, timeout=TIMEOUT_SECONDS)
    with open(app, "a", encoding="utf-8") as f:
        f.write("\n\ndef live():\n    return True\n")
    return project


def posix_copy(plugin_dir, scratch):
    """A copy of the plugin folder as a POSIX checkout has it. .gitattributes leaves the line
    endings of the .cmd hook wrapper to core.autocrlf, because cmd.exe runs it on Windows. So a
    checkout with core.autocrlf=true has CRLF there, which /bin/sh cannot run, and no POSIX host
    runs such a copy. Every other hook file is LF in every checkout."""
    copy = os.path.join(scratch, "plugin")
    shutil.copytree(plugin_dir, copy, symlinks=True)
    for dirpath, _, names in os.walk(copy):
        for name in names:
            path = os.path.join(dirpath, name)
            if name.endswith(".cmd") and not os.path.islink(path):
                with open(path, "rb") as f:
                    data = f.read()
                with open(path, "wb") as f:
                    f.write(data.replace(b"\r\n", b"\n"))
    return copy


def cursor_payload(event, project):
    """The payload that Cursor sends: its common fields and those of the event."""
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
    return json.dumps(data, separators=(",", ":"))


def variants(event):
    """(label, payload kind, inherited CLAUDECODE, run in the project) of each run of a hook.
    The first is the run that Cursor makes. The others are runs that a hook must also not act
    in: Cursor started from a Claude Code shell (CLAUDECODE inherited), a Claude Code payload,
    and the project as the working folder of an event that Cursor runs in the plugin folder."""
    faithful_in_project = event in PROJECT_EVENTS
    found = [("Cursor run", None, False, faithful_in_project),
             ("Cursor started from a Claude Code shell", None, True, faithful_in_project)]
    found += [(label, data, False, faithful_in_project) for label, data in CLAUDE_PAYLOADS.get(event, [])]
    if not faithful_in_project:
        found += [(f"{label}, in the project", data, inherited, True) for label, data, inherited, _ in list(found)]
    return found


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


def tree_digest(folder):
    """The sha256 of every path, mode, link target and content under the folder."""
    digest = hashlib.sha256()
    for dirpath, dirnames, names in sorted(os.walk(folder)):
        dirnames.sort()
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            digest.update(os.path.relpath(full, folder).encode() + b"\0")
            if os.path.islink(full):
                digest.update(b"link:" + os.readlink(full).encode())
            else:
                digest.update(oct(os.stat(full).st_mode & 0o777).encode())
                with open(full, "rb") as f:
                    digest.update(hashlib.sha256(f.read()).digest())
    return digest.hexdigest()


def run_once(plugin_copy, scratch, event, command, variant):
    """One run of the hook in a new project and HOME; a Result."""
    label, claude_data, inherited, in_project = variant
    root = tempfile.mkdtemp(prefix="run-", dir=scratch)
    project = make_project(root)
    home = os.path.join(root, "home")
    os.makedirs(home)
    command = command.replace("${CURSOR_PLUGIN_ROOT}", plugin_copy).replace("${CLAUDE_PLUGIN_ROOT}", plugin_copy)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()), "HOME": home,
        "CURSOR_PROJECT_DIR": project, "CURSOR_VERSION": CURSOR_VERSION, "CLAUDE_PROJECT_DIR": project,
        "CURSOR_PLUGIN_ROOT": plugin_copy, "CLAUDE_PLUGIN_ROOT": plugin_copy,
    }
    if inherited:
        env["CLAUDECODE"] = "1"
    if claude_data is None:
        stdin = cursor_payload(event, project)
    else:
        stdin = json.dumps({"session_id": "hook-probe", "transcript_path": None, "cwd": project, **claude_data})
    before = files_of(project, home)
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=project if in_project else plugin_copy, env=env,
                          input=stdin, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    after = files_of(project, home)
    written = sorted(os.path.relpath(path, root) for path in after if before.get(path) != after[path])
    stdout = proc.stdout.strip()
    return Result(bool(stdout) or bool(written) or proc.returncode != 0, proc.returncode, stdout, written, label)


def probe(plugin_dir, event, command, faithful_only=False):
    """Run the command of one hook of the plugin folder as Cursor runs it for the event, and in
    the other variants (see variants). The Result of the first run that acts, else that of the
    Cursor run. With faithful_only, only the Cursor run. Raises OSError or
    subprocess.SubprocessError when the hook cannot run at all."""
    plugin_dir = os.path.abspath(plugin_dir)
    key = (tree_digest(plugin_dir), event, command, faithful_only)
    if key not in _cache:
        with tempfile.TemporaryDirectory(prefix="cursor-hook-probe-") as scratch:
            plugin_copy = posix_copy(plugin_dir, scratch)
            results = []
            for variant in variants(event)[:1] if faithful_only else variants(event):
                results.append(run_once(plugin_copy, scratch, event, command, variant))
                if results[-1].acts and not faithful_only:
                    break
            _cache[key] = next((r for r in results if r.acts), results[0])
    return _cache[key]


def followup_message(result):
    """The followup_message that a stop hook printed, or None."""
    try:
        message = json.loads(result.stdout).get("followup_message")
    except (ValueError, AttributeError):
        return None
    return message if isinstance(message, str) and message.strip() else None


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    plugin_dir, event, command = sys.argv[1:]
    for label, result in (("any variant", probe(plugin_dir, event, command)),
                          ("Cursor run", probe(plugin_dir, event, command, faithful_only=True))):
        print(json.dumps({"probe": label, **result._asdict()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
