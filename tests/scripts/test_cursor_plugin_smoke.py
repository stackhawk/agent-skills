"""scripts/cursor-plugin-smoke.sh against a stub Cursor CLI.

The live smoke needs a Cursor login or CURSOR_API_KEY, so these cases replace `cursor-agent`
with a stub that records its --plugin-dir and prints a stream-json answer: one answer with
the plugin and another for the control run without it. They check the parts of the script
that do not need Cursor: the plugin path the CLI receives (it runs inside a scratch
workspace, so the path must be absolute), the skill names it expects from the plugin's
manifest, the pass, fail and inconclusive results, and exit 77 when the CLI or its
authentication is missing.
"""
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "cursor-plugin-smoke.sh")

BUILT_IN = "SKILL: create-rule\\nSKILL: loop"
WINGMAN = ["hawkscan", "stackhawk-api", "stackhawk-data-seed", "stackhawk-optimize"]
STUB = """#!/usr/bin/env bash
dir=""
while [ $# -gt 0 ]; do
  case "$1" in --plugin-dir) dir="$2"; shift 2 ;; *) shift ;; esac
done
if [ -n "${STUB_AUTH_FAIL:-}" ]; then
  echo "Error: Authentication required. Please run 'agent login' first." >&2
  exit 1
fi
answer="$STUB_CONTROL"
if [ -n "$dir" ]; then
  echo "$dir" > "$STUB_LOG"
  [ -f "$dir/.cursor-plugin/plugin.json" ] || { echo "no plugin at $dir" >&2; exit 3; }
  answer="$STUB_ANSWER"
fi
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\\n' "$answer"
"""


def skills(*names):
    return "\\n".join(f"SKILL: {name}" for name in names)


def run(tmp_path, plugin_arg, answer, control=BUILT_IN, auth_fail=False, with_cli=True):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for tool in ("bash", "git", "python3", "mkdir", "rm", "grep", "tr", "mktemp", "dirname"):
        if not (bindir / tool).exists():
            os.symlink(shutil.which(tool), bindir / tool)
    if with_cli:
        stub = bindir / "cursor-agent"
        stub.write_text(STUB)
        stub.chmod(0o755)
    env = {
        "PATH": str(bindir), "HOME": str(tmp_path),
        "STUB_LOG": str(tmp_path / "plugin-dir.txt"),
        "STUB_ANSWER": answer, "STUB_CONTROL": control,
    }
    if auth_fail:
        env["STUB_AUTH_FAIL"] = "1"
    return subprocess.run(["bash", SCRIPT, plugin_arg, str(tmp_path / "out")], cwd=REPO_ROOT,
                          env=env, capture_output=True, text=True, timeout=60, check=False)


def test_relative_plugin_path_reaches_the_cli_as_an_absolute_path(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan", answer=BUILT_IN + "\\n" + skills("hawkscan"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    received = (tmp_path / "plugin-dir.txt").read_text().strip()
    assert received == os.path.join(REPO_ROOT, "plugins/hawkscan")
    assert "PASS" in proc.stdout


def test_a_skill_of_the_plugin_that_is_not_listed_fails(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan", answer=BUILT_IN)
    assert proc.returncode == 1
    assert "did not list these skills of the plugin: hawkscan" in proc.stderr


def test_wingman_needs_the_four_bundled_skills_from_its_manifest_path(tmp_path):
    proc = run(tmp_path, "cursor-plugins/wingman", answer=skills(*WINGMAN[:3]))
    assert proc.returncode == 1
    assert "stackhawk-optimize" in proc.stderr
    proc = run(tmp_path, "cursor-plugins/wingman", answer=skills(*WINGMAN))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_names_match_without_case_backticks_or_a_namespace(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan", answer="SKILL: `hawkscan:HawkScan`")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_control_that_already_lists_every_skill_is_inconclusive(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan", answer=skills("hawkscan"),
               control=BUILT_IN + "\\n" + skills("hawkscan", "api"))
    assert proc.returncode == 77, proc.stdout + proc.stderr
    assert "control already lists every skill" in proc.stdout


def test_one_skill_absent_from_the_control_is_enough(tmp_path):
    proc = run(tmp_path, "cursor-plugins/wingman", answer=skills(*WINGMAN),
               control=skills("hawkscan", "api"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "absent without it: stackhawk-api stackhawk-data-seed stackhawk-optimize" in proc.stdout


@pytest.mark.parametrize("case", ["no-auth", "no-cli"])
def test_skips_without_the_cli_or_authentication(tmp_path, case):
    proc = run(tmp_path, "plugins/hawkscan", answer=skills("hawkscan"),
               auth_fail=case == "no-auth", with_cli=case == "no-auth")
    assert proc.returncode == 77, proc.stdout + proc.stderr
    assert "SKIP" in proc.stdout


def test_a_folder_without_a_cursor_manifest_fails(tmp_path):
    proc = run(tmp_path, "plugins/wingman", answer=skills("hawkscan"))
    assert proc.returncode == 1
    assert ".cursor-plugin/plugin.json" in proc.stderr
