"""The Cursor eval harness must test the layout users install, with the Cursor CLI.

The harness once copied only the 28 generated rules into each run's workspace (no skills,
no hook), so its published baseline measured a layout that the installer no longer ships.
It also launched `agent`, a name another tool's CLI can take on PATH. It now runs
`scripts/install.sh --platform cursor` into the workspace and prefers `cursor-agent`.
"""
import importlib
import os
import subprocess
from unittest import mock

from evals.lib.models import ParsedRun

# Tests use this module object and its ADAPTER, so that a patch on the module reaches launch().
cursor_module = importlib.import_module("evals.harnesses.cursor.adapter")


def files_under(root):
    return {
        os.path.relpath(os.path.join(d, f), root)
        for d, _dirs, files in os.walk(root)
        for f in files
    }


def test_setup_installs_the_user_layout(tmp_path):
    assert cursor_module._setup_skill(str(tmp_path)) is None
    files = files_under(tmp_path / ".cursor")
    assert {"rules/stackhawk.mdc", "rules/stackhawk-config.mdc", "hooks.json", "hooks/stackhawk-stop.sh"} <= files
    skills = {f.split("/")[1] for f in files if f.startswith("skills/")}
    assert skills == {"hawkscan", "api", "hawkscan-ci", "stackhawk-data-seed", "optimize"}
    assert not any(f.startswith("rules/stackhawk-hawkscan") for f in files), "no legacy rules"


def test_setup_failure_is_reported(tmp_path):
    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with mock.patch("subprocess.run", return_value=failed):
        assert "boom" in cursor_module._setup_skill(str(tmp_path))


def test_prefers_cursor_agent():
    with mock.patch("shutil.which", lambda name: "/bin/x" if name == "cursor-agent" else None):
        assert cursor_module._agent_binary() == "cursor-agent"
    with mock.patch("shutil.which", lambda name: None):
        assert cursor_module._agent_binary() == "agent"


def test_launch_uses_the_chosen_binary_and_skips_setup_without_the_skill():
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    adapter = cursor_module.ADAPTER
    with mock.patch.object(cursor_module, "_agent_binary", return_value="fake-cursor-cli"), \
            mock.patch("subprocess.run", fake_run):
        run = adapter.launch("hi", "hawkscan", "x", [], model=None, load_skill=False,
                             max_budget=0.2, bare=False, full_auto=False)
    assert isinstance(run, ParsedRun)
    assert len(calls) == 1, "no install when the skill is not loaded"
    assert calls[0][0] == "fake-cursor-cli"


def test_launch_stops_when_setup_fails():
    adapter = cursor_module.ADAPTER
    with mock.patch.object(cursor_module, "_setup_skill", return_value="cursor install failed: x"), \
            mock.patch("subprocess.run", side_effect=AssertionError("agent must not run")):
        run = adapter.launch("hi", "hawkscan", "x", [], model=None, load_skill=True,
                             max_budget=0.2, bare=False, full_auto=False)
    assert run.error == "cursor install failed: x"
