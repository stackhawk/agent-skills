import json, subprocess, sys, os, pathlib, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "finishing-work-nudge.sh"

def run(command, changed_files, marker_dir):
    ev = {"tool_name":"Bash","tool_input":{"command":command}}
    env = dict(os.environ, BENCHMARK_HOOK_CHANGED_FILES="\n".join(changed_files),
               BENCHMARK_HOOK_MARKER_DIR=marker_dir)
    p = subprocess.run(["bash", str(HOOK)], input=json.dumps(ev), capture_output=True, text=True, env=env)
    return p.returncode, p.stdout

class TestHook(unittest.TestCase):
    def setUp(self): self.m = tempfile.mkdtemp()
    def test_commit_touching_skill_nudges(self):
        rc, out = run("git commit -m x", ["plugins/hawkscan/skills/hawkscan/SKILL.md"], self.m)
        self.assertEqual(rc, 0); self.assertIn("/benchmark", out)
    def test_commit_not_touching_skill_silent(self):
        rc, out = run("git commit -m x", ["README.md"], self.m)
        self.assertEqual(rc, 0); self.assertNotIn("/benchmark", out.strip())
    def test_non_finishing_command_silent(self):
        rc, out = run("ls -la", ["plugins/hawkscan/skills/hawkscan/SKILL.md"], self.m)
        self.assertEqual(rc, 0); self.assertNotIn("/benchmark", out.strip())
    def test_dedup_second_call_silent(self):
        run("git commit -m x", ["plugins/hawkscan/skills/hawkscan/SKILL.md"], self.m)
        rc, out = run("gh pr create", ["plugins/hawkscan/skills/hawkscan/SKILL.md"], self.m)
        self.assertEqual(rc, 0); self.assertNotIn("/benchmark", out.strip())
