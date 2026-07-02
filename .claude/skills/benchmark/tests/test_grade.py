import json, pathlib, shutil, subprocess, sys, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import grade

FX = pathlib.Path(__file__).resolve().parent / "fixtures"
# ground truth whose answer keys match the DISCOVERY block in the fixtures
GT = {"app": "x", "run_command": "", "host": "", "api_style": "", "spa": "", "auth": "",
      "evidence": {}}


class TestParse(unittest.TestCase):
    def test_parse_collects_tools_events_and_final(self):
        p = grade.parse_transcript(FX / "transcript_new.jsonl")
        self.assertEqual([t["name"] for t in p["tool_calls"]], ["Read", "Read", "Read", "Grep"])
        self.assertIn("README.md", p["tool_calls"][0]["target"])
        self.assertIn("DISCOVERY:", p["final_text"])
        self.assertTrue(any(e["kind"] == "tool" for e in p["events"]))


class TestCoreChecks(unittest.TestCase):
    """The core is hypothesis-AGNOSTIC — only these 4 signals, no discovery specifics."""
    def setUp(self):
        self.c = grade.process_checks(grade.parse_transcript(FX / "transcript_new.jsonl"), GT)

    def test_only_core_signals_present(self):
        self.assertEqual(set(self.c), {"read_agent_docs", "exploration_breadth",
                                       "emitted_expected_answers", "stayed_read_only"})

    def test_read_agent_docs(self):
        self.assertTrue(self.c["read_agent_docs"])

    def test_breadth_counts_distinct_reads(self):
        self.assertEqual(self.c["exploration_breadth"], 4)

    def test_stayed_read_only_defaults_true(self):
        self.assertTrue(self.c["stayed_read_only"])


class TestEmittedExpectedAnswers(unittest.TestCase):
    """emitted_expected_answers is derived from the ground-truth keys, not hard-coded."""
    def test_true_when_final_mentions_all_gt_keys(self):
        c = grade.process_checks(grade.parse_transcript(FX / "transcript_new.jsonl"), GT)
        self.assertTrue(c["emitted_expected_answers"])

    def test_false_when_a_gt_key_is_missing_from_final(self):
        gt2 = {**GT, "cache_backend": ""}  # a key the DISCOVERY block never mentions
        c = grade.process_checks(grade.parse_transcript(FX / "transcript_new.jsonl"), gt2)
        self.assertFalse(c["emitted_expected_answers"])

    def test_answer_keys_excludes_metadata(self):
        self.assertEqual(grade.answer_keys(GT), ["run_command", "host", "api_style", "spa", "auth"])


class TestCustomChecks(unittest.TestCase):
    """A benchmark supplies hypothesis-specific signals via checks.py; the app-discovery
    signals (docs-before-conclusion, legacy-menu) now live HERE as a per-benchmark plugin,
    not in core."""
    CHECKS_PY = '''
import re
CONCL = re.compile(r"DISCOVERY:|api_style:|host:\\s*http", re.I)
DOC = re.compile(r"README|CLAUDE\\.md|AGENTS\\.md", re.I)
LEGACY = re.compile(r"node -e .*(react|vue|spa)|@PreAuthorize|AddAuthentication\\(", re.I)

def checks(parsed, ground_truth):
    events = parsed.get("events", [])
    first_doc = first_concl = None
    for i, e in enumerate(events):
        if e.get("kind") == "tool" and DOC.search(e.get("target") or "") and first_doc is None:
            first_doc = i
        if e.get("kind") == "text" and CONCL.search(e.get("text") or "") and first_concl is None:
            first_concl = i
    all_cmds = " ".join(c["target"] for c in parsed["tool_calls"])
    return {
        "docs_before_conclusion": first_doc is not None and (first_concl is None or first_doc < first_concl),
        "ran_legacy_command_menu": bool(LEGACY.search(all_cmds)),
    }
'''

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "checks.py").write_text(self.CHECKS_PY)
        self.fn = grade.load_custom_checks(str(self.tmp / "checks.py"))

    def test_loads_the_checks_callable(self):
        self.assertTrue(callable(self.fn))

    def test_missing_checks_py_returns_none(self):
        self.assertIsNone(grade.load_custom_checks(str(self.tmp / "nope.py")))
        self.assertIsNone(grade.load_custom_checks(""))

    def test_pigeonhole_flagged_by_custom_check(self):
        # transcript_pigeonhole asserts a conclusion in text BEFORE reading any doc
        out = self.fn(grade.parse_transcript(FX / "transcript_pigeonhole.jsonl"), GT)
        self.assertFalse(out["docs_before_conclusion"])

    def test_docs_first_passes_custom_check(self):
        out = self.fn(grade.parse_transcript(FX / "transcript_new.jsonl"), GT)
        self.assertTrue(out["docs_before_conclusion"])

    def test_legacy_menu_detected_on_old_arm(self):
        out = self.fn(grade.parse_transcript(FX / "transcript_old.jsonl"), GT)
        self.assertTrue(out["ran_legacy_command_menu"])
        out2 = self.fn(grade.parse_transcript(FX / "transcript_new.jsonl"), GT)
        self.assertFalse(out2["ran_legacy_command_menu"])


class TestGradeCliMerge(unittest.TestCase):
    """End-to-end via the grade.py CLI (--no-judge): the checks.py merge, its
    fail-safe degradation, and core-wins-on-collision."""
    def _run(self, checks_py_body):
        cell = pathlib.Path(tempfile.mkdtemp())
        shutil.copy(FX / "transcript_new.jsonl", cell / "transcript.jsonl")
        (cell / "gt.json").write_text(json.dumps(GT))
        (cell / "checks.py").write_text(checks_py_body)
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "grade.py"), "--cell", str(cell),
             "--app", "x", "--ground-truth", str(cell / "gt.json"),
             "--checks", str(cell / "checks.py"), "--no-judge"],
            capture_output=True, text=True)
        return p, json.loads((cell / "checks.json").read_text())

    def test_custom_signal_merges_with_core(self):
        p, c = self._run("def checks(p, g):\n    return {'my_extra_signal': True}\n")
        self.assertEqual(p.returncode, 0)
        self.assertTrue(c["my_extra_signal"])
        self.assertIn("read_agent_docs", c)  # core still present

    def test_raising_checks_degrades_to_core_without_aborting(self):
        p, c = self._run("def checks(p, g):\n    raise RuntimeError('boom')\n")
        self.assertEqual(p.returncode, 0)          # run did not abort
        self.assertIn("read_agent_docs", c)         # core signals still written
        self.assertNotIn("my_extra_signal", c)
        self.assertIn("custom checks.py failed", p.stderr)

    def test_core_wins_on_name_collision(self):
        # a checks.py trying to clobber a core signal must not win
        p, c = self._run("def checks(p, g):\n    return {'read_agent_docs': 'HIJACK'}\n")
        self.assertEqual(p.returncode, 0)
        self.assertIsInstance(c["read_agent_docs"], bool)


class TestJudgeParsing(unittest.TestCase):
    def test_parses_fenced_json(self):
        out = grade.parse_judge_output('```json\n{"exploratory_score":3,"pigeonholed":false}\n```')
        self.assertEqual(out["exploratory_score"], 3)

    def test_parses_bare_json_with_prose(self):
        out = grade.parse_judge_output('verdict: {"exploratory_score":1,"pigeonholed":true} done')
        self.assertTrue(out["pigeonholed"])


class TestJudgePrompt(unittest.TestCase):
    def test_prompt_includes_ground_truth_and_gt_derived_fields(self):
        pr = grade.build_judge_prompt("final", "excerpt", GT)
        self.assertIn("exploratory_score", pr)
        self.assertIn("run_command", pr)   # correctness fields derived from GT keys
        self.assertIn("auth", pr)


class TestTaskCompletionPrompt(unittest.TestCase):
    def test_prompt_has_diff_and_metrics(self):
        cell = pathlib.Path(tempfile.mkdtemp())
        (cell / "transcript.jsonl").write_text('{"type":"result","result":"fixed the SQLi"}\n')
        (cell / "fix.diff").write_text("--- a/x\n+++ b/x\n+ safe query")
        captured = {}
        orig = grade.run_judge
        grade.run_judge = lambda p, m: captured.setdefault("p", p) or {"close_rate": 1.0}
        try:
            grade.grade_task_completion(str(cell), {"app": "x", "vulns": ["sqli"]}, "m")
        finally:
            grade.run_judge = orig
        self.assertIn("safe query", captured["p"])
        self.assertIn("close_rate", captured["p"])


if __name__ == "__main__":
    unittest.main()
