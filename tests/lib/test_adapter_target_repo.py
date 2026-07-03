import json
import unittest
from unittest import mock

from evals.lib.harness import get_adapter
from evals.lib.models import TargetRepo

cc_adapter = get_adapter("claude-code")


class AdapterTargetRepo(unittest.TestCase):
    def _fake_run(self, calls):
        def _run(cmd, *a, **k):
            calls.append((cmd, k))
            class R:
                returncode = 0
                stdout = json.dumps({"type": "result", "result": "DISCOVERY:\ntechnology: Go"})
                stderr = "Denied (read-only discovery): Write would modify files\n"
            return R()
        return _run

    def test_clones_and_captures_denials(self):
        calls = []
        tr = TargetRepo(url="https://example.com/x.git", pin="deadbeef")
        with mock.patch("subprocess.run", self._fake_run(calls)):
            run = cc_adapter.launch("discover", "hawkscan", "x", ["/plug"],
                                    model=None, load_skill=True, max_budget=0.2,
                                    bare=False, full_auto=False, target_repo=tr)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        self.assertTrue(any("clone" in c and "deadbeef" not in c for c in cmds),
                        "expected a git clone call")
        self.assertTrue(any("deadbeef" in c for c in cmds),
                        "expected a git checkout of the pin")
        self.assertTrue(run.guard_denials, "guard denials should be captured")

    def test_no_target_repo_is_unchanged(self):
        calls = []
        with mock.patch("subprocess.run", self._fake_run(calls)):
            run = cc_adapter.launch("hi", "hawkscan", "hw-01", ["/plug"],
                                    model=None, load_skill=True, max_budget=0.2,
                                    bare=False, full_auto=False)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        self.assertFalse(any("clone" in c for c in cmds), "no clone without target_repo")
        self.assertEqual(run.guard_denials, [])


if __name__ == "__main__":
    unittest.main()
