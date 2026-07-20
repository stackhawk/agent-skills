import unittest
from evals.lib.models import ParsedRun
from evals.lib.grading import run_process_checks

CHECK = [{"id": "stayed_read_only", "type": "guard_clean", "severity": "blocking"}]


class GuardCleanCheck(unittest.TestCase):
    def test_passes_when_no_denials(self):
        run = ParsedRun(output_text="done", guard_denials=[])
        res = run_process_checks(run, CHECK)
        self.assertTrue(res[0].passed)

    def test_fails_when_denied(self):
        run = ParsedRun(output_text="done",
                        guard_denials=["Denied (read-only discovery): Write would modify files"])
        res = run_process_checks(run, CHECK)
        self.assertFalse(res[0].passed)
        self.assertEqual(res[0].severity, "blocking")

    def test_fail_surfaces_denial_reasons_in_anti_found(self):
        run = ParsedRun(output_text="done", guard_denials=[
            "Denied (read-only discovery): Write would modify files",
            "Denied (read-only discovery): hawk scan is out of scope for discovery",
        ])
        res = run_process_checks(run, CHECK)
        self.assertFalse(res[0].passed)
        self.assertIsNotNone(res[0].anti_found)
        self.assertIn("Write would modify files", res[0].anti_found)
        self.assertIn("hawk scan is out of scope", res[0].anti_found)

    def test_pass_has_no_anti_found(self):
        run = ParsedRun(output_text="done", guard_denials=[])
        res = run_process_checks(run, CHECK)
        self.assertTrue(res[0].passed)
        self.assertIsNone(res[0].anti_found)


APP_START = "Denied (read-only discovery): starting the app/server/container is out of scope for read-only discovery"
WRITE = "Denied (read-only discovery): Write would modify files"


class GuardScopeClassification(unittest.TestCase):
    """A blocked-and-recovered app-START attempt is a soft foul; a write/scan/egress
    denial is a hard foul. `guard_scope` lets a check assert one flavor."""

    def _check(self, scope):
        return [{"id": "c", "type": "guard_clean", "severity": "blocking", "guard_scope": scope}]

    def test_hard_scope_ignores_app_start(self):
        run = ParsedRun(output_text="done", guard_denials=[APP_START])
        self.assertTrue(run_process_checks(run, self._check("hard"))[0].passed)

    def test_hard_scope_fails_on_write(self):
        run = ParsedRun(output_text="done", guard_denials=[WRITE])
        self.assertFalse(run_process_checks(run, self._check("hard"))[0].passed)

    def test_hard_scope_fails_on_mixed(self):
        run = ParsedRun(output_text="done", guard_denials=[APP_START, WRITE])
        res = run_process_checks(run, self._check("hard"))[0]
        self.assertFalse(res.passed)
        self.assertIn("Write would modify files", res.anti_found)
        self.assertNotIn("starting the app", res.anti_found)  # app-start not surfaced under hard scope

    def test_app_start_scope_flags_app_start(self):
        run = ParsedRun(output_text="done", guard_denials=[APP_START])
        self.assertFalse(run_process_checks(run, self._check("app_start"))[0].passed)

    def test_app_start_scope_ignores_write(self):
        run = ParsedRun(output_text="done", guard_denials=[WRITE])
        self.assertTrue(run_process_checks(run, self._check("app_start"))[0].passed)


if __name__ == "__main__":
    unittest.main()
