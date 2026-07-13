import json
import os
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
        claude_cmd = next(c for c in cmds if c.strip().startswith("claude "))
        self.assertIn("--max-budget-usd 2.0", claude_cmd,
                      "target_repo cells get the higher discovery budget, not the 0.2 cap")

    def test_checkout_failure_returns_error(self):
        calls = []

        def _run(cmd, *a, **k):
            calls.append((cmd, k))
            joined = " ".join(cmd) if isinstance(cmd, list) else cmd

            class R:
                returncode = 1 if "checkout" in joined else 0
                stdout = ""
                stderr = "error: pathspec 'deadbeef' did not match any file(s) known to git\n"

            return R()

        tr = TargetRepo(url="https://example.com/x.git", pin="deadbeef")
        with mock.patch("subprocess.run", _run):
            run = cc_adapter.launch("discover", "hawkscan", "x", ["/plug"],
                                    model=None, load_skill=True, max_budget=0.2,
                                    bare=False, full_auto=False, target_repo=tr)
        self.assertIsNotNone(run.error)
        self.assertIn("checkout failed", run.error)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        self.assertFalse(any(c.strip().startswith("claude ") for c in cmds),
                         "should not launch claude after a checkout failure")

    def test_research_token_injected_then_scrubbed(self):
        calls = []
        tr = TargetRepo(url="https://github.com/stackhawk-research/x.git", pin="deadbeef")
        with mock.patch.dict(os.environ, {"RESEARCH_REPO_TOKEN": "TESTTOKEN"}):
            with mock.patch("subprocess.run", self._fake_run(calls)):
                cc_adapter.launch("discover", "hawkscan", "x", ["/plug"],
                                  model=None, load_skill=True, max_budget=0.2,
                                  bare=False, full_auto=False, target_repo=tr)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        # token embedded in the adapter's OWN clone only
        self.assertTrue(any("clone" in c and "x-access-token:TESTTOKEN@github.com" in c
                            for c in cmds), "clone should carry the token")
        # remote (with the token URL) dropped before the agent runs
        self.assertTrue(any("remote remove origin" in c for c in cmds),
                        "token-bearing remote should be scrubbed")
        # the agent subprocess env must NOT carry the token
        claude_call = next(c for c in calls
                           if (c[0][0] if isinstance(c[0], list) else c[0]).startswith("claude"))
        agent_env = claude_call[1].get("env", {})
        self.assertNotIn("RESEARCH_REPO_TOKEN", agent_env,
                         "clone token must not leak into the agent env")

    def test_no_token_clones_plainly(self):
        calls = []
        tr = TargetRepo(url="https://github.com/stackhawk-research/x.git", pin="deadbeef")
        env_no_tok = {k: v for k, v in os.environ.items() if k != "RESEARCH_REPO_TOKEN"}
        with mock.patch.dict(os.environ, env_no_tok, clear=True):
            with mock.patch("subprocess.run", self._fake_run(calls)):
                cc_adapter.launch("discover", "hawkscan", "x", ["/plug"],
                                  model=None, load_skill=True, max_budget=0.2,
                                  bare=False, full_auto=False, target_repo=tr)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        self.assertFalse(any("x-access-token" in c for c in cmds),
                         "no token env -> plain clone URL")

    def test_no_target_repo_is_unchanged(self):
        calls = []
        with mock.patch("subprocess.run", self._fake_run(calls)):
            run = cc_adapter.launch("hi", "hawkscan", "hw-01", ["/plug"],
                                    model=None, load_skill=True, max_budget=0.2,
                                    bare=False, full_auto=False)
        cmds = [" ".join(c[0]) if isinstance(c[0], list) else c[0] for c in calls]
        self.assertFalse(any("clone" in c for c in cmds), "no clone without target_repo")
        self.assertEqual(run.guard_denials, [])
        claude_cmd = next(c for c in cmds if c.strip().startswith("claude "))
        self.assertIn("--max-budget-usd 0.2", claude_cmd,
                      "scan cells keep the passed-in runtime budget cap")


class NonClaudeAdapterTargetRepo(unittest.TestCase):
    """The non-claude adapters must ACCEPT the target_repo kwarg (the CLI passes
    it on every launch) and short-circuit discovery cells cleanly. Regression for
    the PLUMBING FAILURE where cli.py passed target_repo=... to launch() but only
    claude-code's signature accepted it, so every cell on codex/cursor/agy raised
    TypeError and 0/N ran cleanly."""

    ADAPTERS = ("codex", "cursor", "agy")

    def test_launch_accepts_target_repo_kwarg(self):
        # No target_repo: launch() must accept the keyword without raising a
        # TypeError just for its presence in the signature. We don't run the
        # agent here; a raised TypeError would name the bad kwarg.
        import inspect
        for name in self.ADAPTERS:
            adapter = get_adapter(name)
            params = inspect.signature(adapter.launch).parameters
            self.assertIn("target_repo", params,
                          f"{name} adapter.launch must accept target_repo")

    def test_discovery_cell_short_circuits_without_shelling_out(self):
        tr = TargetRepo(url="https://github.com/stackhawk-research/x.git", pin="deadbeef")
        for name in self.ADAPTERS:
            adapter = get_adapter(name)
            calls = []
            with mock.patch("subprocess.run",
                            lambda cmd, *a, **k: calls.append(cmd)):
                run = adapter.launch("discover", "hawkscan", "x", ["/plug"],
                                     model=None, load_skill=True, max_budget=0.2,
                                     bare=False, full_auto=False, target_repo=tr)
            self.assertIsNotNone(run.error,
                                 f"{name}: discovery cell should return an error, not run")
            self.assertIn("claude-code", run.error,
                          f"{name}: error should explain discovery is claude-code only")
            self.assertEqual(calls, [],
                             f"{name}: must not shell out for an unsupported discovery cell")


if __name__ == "__main__":
    unittest.main()
