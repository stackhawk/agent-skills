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


if __name__ == "__main__":
    unittest.main()
