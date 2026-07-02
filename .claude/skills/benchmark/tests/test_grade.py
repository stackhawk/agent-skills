import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import grade
FX = pathlib.Path(__file__).resolve().parent / "fixtures"

class TestParse(unittest.TestCase):
    def test_parse_collects_tool_targets_and_final(self):
        p = grade.parse_transcript(FX / "transcript_new.jsonl")
        names = [t["name"] for t in p["tool_calls"]]
        self.assertEqual(names, ["Read","Read","Read","Grep"])
        self.assertIn("README.md", p["tool_calls"][0]["target"])
        self.assertIn("DISCOVERY:", p["final_text"])

class TestChecksNew(unittest.TestCase):
    def setUp(self): self.c = grade.process_checks(grade.parse_transcript(FX / "transcript_new.jsonl"))
    def test_read_agent_docs(self): self.assertTrue(self.c["read_agent_docs"])
    def test_docs_before_conclusion(self): self.assertTrue(self.c["docs_before_conclusion"])
    def test_explored_manifests(self): self.assertTrue(self.c["explored_manifests"])
    def test_breadth(self): self.assertEqual(self.c["exploration_breadth"], 4)
    def test_five_answers(self): self.assertTrue(self.c["emitted_five_answers"])
    def test_read_only(self): self.assertTrue(self.c["stayed_read_only"])
    def test_no_legacy_menu(self): self.assertFalse(self.c["ran_legacy_command_menu"])

class TestChecksOld(unittest.TestCase):
    def setUp(self): self.c = grade.process_checks(grade.parse_transcript(FX / "transcript_old.jsonl"))
    def test_no_docs(self): self.assertFalse(self.c["read_agent_docs"])
    def test_legacy_menu(self): self.assertTrue(self.c["ran_legacy_command_menu"])
    def test_docs_before_conclusion_false(self): self.assertFalse(self.c["docs_before_conclusion"])

class TestChecksPigeonhole(unittest.TestCase):
    def setUp(self): self.c = grade.process_checks(grade.parse_transcript(FX / "transcript_pigeonhole.jsonl"))
    def test_read_docs_true(self): self.assertTrue(self.c["read_agent_docs"])
    def test_docs_before_conclusion_false(self): self.assertFalse(self.c["docs_before_conclusion"])

class TestJudgeParsing(unittest.TestCase):
    def test_parses_fenced_json(self):
        out = grade.parse_judge_output('```json\n{"exploratory_score":3,"pigeonholed":false,"correctness":{}}\n```')
        self.assertEqual(out["exploratory_score"], 3)
    def test_parses_bare_json_with_prose(self):
        out = grade.parse_judge_output('Here is my verdict: {"exploratory_score":1,"pigeonholed":true,"correctness":{}} done')
        self.assertTrue(out["pigeonholed"])

class TestJudgePrompt(unittest.TestCase):
    def test_prompt_includes_ground_truth_and_answers(self):
        pr = grade.build_judge_prompt("DISCOVERY:\nhost: x", "excerpt", {"host": "http://localhost:8080"})
        self.assertIn("localhost:8080", pr)
        self.assertIn("exploratory_score", pr)

class TestTaskCompletionPrompt(unittest.TestCase):
    def test_prompt_has_diff_and_metrics(self):
        import grade, json, tempfile, pathlib
        cell = pathlib.Path(tempfile.mkdtemp())
        (cell/"transcript.jsonl").write_text('{"type":"result","result":"fixed the SQLi"}\n')
        (cell/"fix.diff").write_text("--- a/x\n+++ b/x\n+ safe query")
        # build the same prompt the grader would (call the inner builder via monkeypatch-free path):
        # verify grade_task_completion constructs a prompt containing the diff + metric keys by
        # temporarily replacing run_judge to capture its prompt.
        captured = {}
        orig = grade.run_judge
        grade.run_judge = lambda p, m: captured.setdefault("p", p) or {"close_rate": 1.0}
        try:
            grade.grade_task_completion(str(cell), {"expected_vulns": ["sqli"]}, "m")
        finally:
            grade.run_judge = orig
        self.assertIn("safe query", captured["p"])
        self.assertIn("close_rate", captured["p"])
