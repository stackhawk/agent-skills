"""scripts/cursor-plugin-smoke.sh against a stub Cursor CLI.

The live smoke needs CURSOR_API_KEY, so these cases replace `cursor-agent` with a stub that
records its --plugin-dir and prints a stream-json answer. They check the parts of the script
that do not need Cursor: the plugin path the CLI receives (it runs inside a scratch
workspace, so the path must be absolute), the pass and fail checks, and exit 77 when the CLI
or its authentication is missing.
"""
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "cursor-plugin-smoke.sh")

GOOD_ANSWER = "1) hawkscan, api\\n2) # StackHawk skills"
STUB = """#!/usr/bin/env bash
dir=""
while [ $# -gt 0 ]; do
  case "$1" in --plugin-dir) dir="$2"; shift 2 ;; *) shift ;; esac
done
echo "$dir" > "$STUB_LOG"
if [ -n "${STUB_AUTH_FAIL:-}" ]; then
  echo "Error: Authentication required. Please run 'agent login' first." >&2
  exit 1
fi
[ -f "$dir/.cursor-plugin/plugin.json" ] || { echo "no plugin at $dir" >&2; exit 3; }
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\\n' "$STUB_ANSWER"
"""


def run(tmp_path, plugin_arg, answer=GOOD_ANSWER, auth_fail=False, with_cli=True):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for tool in ("bash", "git", "python3", "mkdir", "rm", "grep", "sed", "cat", "mktemp", "dirname"):
        if not (bindir / tool).exists():
            os.symlink(shutil.which(tool), bindir / tool)
    if with_cli:
        stub = bindir / "cursor-agent"
        stub.write_text(STUB)
        stub.chmod(0o755)
    env = {
        "PATH": str(bindir), "HOME": str(tmp_path),
        "STUB_LOG": str(tmp_path / "plugin-dir.txt"), "STUB_ANSWER": answer,
    }
    if auth_fail:
        env["STUB_AUTH_FAIL"] = "1"
    return subprocess.run(["bash", SCRIPT, plugin_arg, str(tmp_path / "out")], cwd=REPO_ROOT,
                          env=env, capture_output=True, text=True, timeout=60)


def test_relative_plugin_path_reaches_the_cli_as_an_absolute_path(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    received = (tmp_path / "plugin-dir.txt").read_text().strip()
    assert received == os.path.join(REPO_ROOT, "plugins/hawkscan")
    assert "PASS" in proc.stdout


def test_missing_router_quote_fails(tmp_path):
    proc = run(tmp_path, "plugins/hawkscan", answer="1) hawkscan")
    assert proc.returncode == 1
    assert "router rule" in proc.stderr


@pytest.mark.parametrize("case", ["no-auth", "no-cli"])
def test_skips_without_the_cli_or_authentication(tmp_path, case):
    proc = run(tmp_path, "plugins/hawkscan", auth_fail=case == "no-auth", with_cli=case == "no-auth")
    assert proc.returncode == 77, proc.stdout + proc.stderr
    assert "SKIP" in proc.stdout


def test_a_folder_without_a_cursor_manifest_fails(tmp_path):
    proc = run(tmp_path, "plugins/wingman/copilot-skills")
    assert proc.returncode == 1
    assert ".cursor-plugin/plugin.json" in proc.stderr
