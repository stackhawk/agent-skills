import unittest
from evals.lib.models import PromptConfig, ParsedRun, ProcessCheckResult, Verdict
from evals.lib.grading import grade_discovery

# A global scan-flow check (no applies_to) + a discovery check (applies_to firefly-iii).
CHECKS = [
    {"id": "preflight_version_check", "type": "command_executed",
     "signals": ["hawk version"], "severity": "blocking"},          # global scan check
    {"id": "discovery_no_legacy_menu", "type": "command_negative",
     "applies_to": ["firefly-iii"], "anti_patterns": ["node -e"], "severity": "warning"},
]


def _p():
    return PromptConfig(id="firefly-iii", should_trigger=True,
                        invocation_type="implicit", prompt="discover",
                        answer_key="answer-keys/firefly-iii.json")


class GradeDiscovery(unittest.TestCase):
    def test_global_scan_checks_do_not_apply(self):
        # Discovery run never ran `hawk version`; the global blocking check must be
        # ignored, so an otherwise-clean cell PASSes.
        run = ParsedRun(output_text="DISCOVERY:\ntechnology: PHP")
        res = grade_discovery(_p(), run, CHECKS, [], platform="claude-code", skill="hawkscan")
        self.assertEqual(res.verdict, Verdict.PASS)
        ids = {c.id for c in res.process_checks}
        self.assertNotIn("preflight_version_check", ids)
        self.assertIn("discovery_no_legacy_menu", ids)

    def test_blocking_judge_check_fails_cell(self):
        run = ParsedRun(output_text="DISCOVERY:\napi_style: REST")
        judge = [ProcessCheckResult(id="answer_key:api_style", passed=False,
                                    severity="blocking")]
        res = grade_discovery(_p(), run, CHECKS, judge, platform="claude-code", skill="hawkscan")
        self.assertEqual(res.verdict, Verdict.FAIL)
        self.assertLessEqual(res.score, 85)

    def test_soft_judge_miss_is_warning_not_fail(self):
        run = ParsedRun(output_text="DISCOVERY:\nauth: token")
        judge = [ProcessCheckResult(id="answer_key:auth", passed=False, severity="warning")]
        res = grade_discovery(_p(), run, CHECKS, judge, platform="claude-code", skill="hawkscan")
        self.assertEqual(res.verdict, Verdict.PASS)
        self.assertLess(res.score, 100)


if __name__ == "__main__":
    unittest.main()
