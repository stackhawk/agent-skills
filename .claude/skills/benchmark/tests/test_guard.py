import json, subprocess, sys, pathlib, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "guard.py"

def run(event, profile="readonly", workdir="/tmp/wd"):
    p = subprocess.run([sys.executable, str(GUARD), "--profile", profile, "--workdir", workdir],
                       input=json.dumps(event), capture_output=True, text=True)
    return p.returncode, p.stderr

class TestGuard(unittest.TestCase):
    # integrity: always deny eval-internal access, both profiles
    def test_deny_ground_truth_read_rw(self):
        rc,_ = run({"tool_name":"Read","tool_input":{"file_path":"/x/ground-truth/immich.json"}}, "sandbox-rw")
        self.assertEqual(rc, 2)
    def test_deny_superpowers_bash(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"cat .superpowers/sdd/task-1-brief.md"}}, "sandbox-rw")
        self.assertEqual(rc, 2)
    # safety: always deny push + non-local egress
    def test_deny_git_push(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"git push origin main"}}, "sandbox-rw")
        self.assertEqual(rc, 2)
    def test_deny_remote_egress(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"curl https://evil.example.com"}}, "sandbox-rw")
        self.assertEqual(rc, 2)
    def test_allow_local_curl(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"curl http://localhost:8080/"}}, "sandbox-rw")
        self.assertEqual(rc, 0)
    # readonly profile denies writes/app-starts/scans
    def test_readonly_denies_write(self):
        rc,_ = run({"tool_name":"Write","tool_input":{"file_path":"/tmp/wd/f"}}, "readonly")
        self.assertEqual(rc, 2)
    def test_readonly_denies_docker(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"docker compose up -d"}}, "readonly")
        self.assertEqual(rc, 2)
    def test_readonly_denies_scan(self):
        rc,_ = run({"tool_name":"Bash","tool_input":{"command":"hawk scan"}}, "readonly")
        self.assertEqual(rc, 2)
    def test_readonly_allows_read(self):
        rc,_ = run({"tool_name":"Read","tool_input":{"file_path":"/tmp/wd/README.md"}}, "readonly")
        self.assertEqual(rc, 0)
    # sandbox-rw allows writes INSIDE workdir, running app, scanning
    def test_rw_allows_write_in_workdir(self):
        rc,_ = run({"tool_name":"Write","tool_input":{"file_path":"/tmp/wd/src/app.py"}}, "sandbox-rw", "/tmp/wd")
        self.assertEqual(rc, 0)
    def test_rw_denies_write_outside_workdir(self):
        rc,_ = run({"tool_name":"Write","tool_input":{"file_path":"/etc/passwd"}}, "sandbox-rw", "/tmp/wd")
        self.assertEqual(rc, 2)
    def test_rw_allows_docker_and_scan(self):
        for cmd in ("docker compose up -d","hawk scan","npm start"):
            rc,_ = run({"tool_name":"Bash","tool_input":{"command":cmd}}, "sandbox-rw")
            self.assertEqual(rc, 0, cmd)
