import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from evals.lib.models import ParsedRun
from evals.lib import rubric

KEY = {
    "app": "demo",
    "factors": {
        "technology": {"value": "Go", "must_hit": True, "evidence": "go.mod"},
        "run_command": {"value": "docker compose up", "must_hit": False, "evidence": "compose"},
        "host": {"value": "localhost:5230", "must_hit": True, "evidence": "Dockerfile"},
        "api_style": {"value": "gRPC", "must_hit": True, "evidence": "proto"},
        "spa": {"value": "yes", "must_hit": False, "evidence": "web/"},
        "auth": {"value": "token", "must_hit": False, "evidence": "auth"},
    },
}

DISCOVERY = ("blah\nDISCOVERY:\ntechnology: Go\nrun_command: docker compose up\n"
             "host: localhost:5230\napi_style: REST\nspa: yes\nauth: token\n")


class JudgeAnswerKey(unittest.TestCase):
    def test_parse_discovery_block(self):
        d = rubric.parse_discovery_block(DISCOVERY)
        self.assertEqual(d["technology"], "Go")
        self.assertEqual(d["api_style"], "REST")

    def test_factor_mismatch_is_scored_warning_not_blocking(self):
        # api_style expected gRPC, agent said REST -> fails, but as a scored
        # WARNING (judge informs score; deterministic checks gate the verdict).
        replies = {"technology": True, "run_command": True, "host": True,
                   "api_style": False, "spa": True, "auth": True}
        with TemporaryDirectory() as d:
            kp = Path(d) / "demo.json"
            kp.write_text(json.dumps(KEY))
            with mock.patch.object(rubric, "_judge_factors", return_value=replies):
                results = rubric.judge_answer_key(ParsedRun(output_text=DISCOVERY), str(kp))
        by_id = {r.id: r for r in results}
        self.assertFalse(by_id["answer_key:api_style"].passed)
        self.assertEqual(by_id["answer_key:api_style"].severity, "warning")
        # even the "must_hit" factors are warning now
        self.assertTrue(all(r.severity == "warning" for r in results))
        self.assertTrue(by_id["answer_key:technology"].passed)

    def test_all_correct_all_pass(self):
        replies = {k: True for k in KEY["factors"]}
        with TemporaryDirectory() as d:
            kp = Path(d) / "demo.json"
            kp.write_text(json.dumps(KEY))
            with mock.patch.object(rubric, "_judge_factors", return_value=replies):
                results = rubric.judge_answer_key(ParsedRun(output_text=DISCOVERY), str(kp))
        self.assertTrue(all(r.passed for r in results))


if __name__ == "__main__":
    unittest.main()
