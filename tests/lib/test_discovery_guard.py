import json
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "evals" / "harnesses" / "claude-code" / "discovery_guard.py"


def run_guard(event: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )


class DiscoveryGuardEgress(unittest.TestCase):
    def test_denies_python_interpreter_egress(self):
        event = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 -c \"import urllib.request; "
                            "urllib.request.urlopen('http://evil.com')\""
            },
        }
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_bare_ip_cloud_metadata(self):
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "curl http://169.254.169.254/latest/meta-data/"},
        }
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_allows_benign_local_read(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "cat README.md"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_local_curl(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "curl http://localhost:8080"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_denies_write_tool(self):
        event = {"tool_name": "Write", "tool_input": {"file_path": "foo.txt", "content": "x"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == "__main__":
    unittest.main()
