import unittest
from evals.lib.models import PromptConfig, TargetRepo, ParsedRun


class TargetRepoModel(unittest.TestCase):
    def test_prompt_without_new_fields_defaults_none(self):
        p = PromptConfig(id="x", should_trigger=True,
                         invocation_type="explicit", prompt="hi")
        self.assertIsNone(p.target_repo)
        self.assertIsNone(p.answer_key)

    def test_prompt_with_target_repo_and_answer_key(self):
        p = PromptConfig(id="firefly-iii", should_trigger=True,
                         invocation_type="implicit", prompt="discover",
                         target_repo={"url": "https://github.com/stackhawk-research/firefly-iii.git",
                                      "pin": "abc123"},
                         answer_key="answer-keys/firefly-iii.json")
        self.assertIsInstance(p.target_repo, TargetRepo)
        self.assertEqual(p.target_repo.pin, "abc123")
        self.assertEqual(p.answer_key, "answer-keys/firefly-iii.json")

    def test_target_repo_rejects_unknown_field(self):
        with self.assertRaises(Exception):
            TargetRepo(url="u", pin="p", branch="oops")

    def test_parsed_run_guard_denials_default_empty(self):
        self.assertEqual(ParsedRun().guard_denials, [])


if __name__ == "__main__":
    unittest.main()
