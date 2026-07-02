import json, pathlib, shutil, subprocess, sys, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import grade

FX = pathlib.Path(__file__).resolve().parent / "fixtures"

# A hypothesis-NEUTRAL benchmark used to prove the engine is generic: made-up
# answer fields that have nothing to do with app-discovery. transcript_generic
# reads a doc + a config + greps, and emits these fields in an ANSWER: block.
NEUTRAL_GT = {"app": "widgetd", "widget_engine": "", "listen_port": "",
              "color_scheme": "", "evidence": {}}
GENERIC = FX / "transcript_generic.jsonl"


class TestParse(unittest.TestCase):
    def test_parse_collects_tools_events_and_final(self):
        p = grade.parse_transcript(GENERIC)
        self.assertEqual([t["name"] for t in p["tool_calls"]], ["Read", "Read", "Grep"])
        self.assertIn("README.md", p["tool_calls"][0]["target"])
        self.assertIn("ANSWER:", p["final_text"])
        self.assertTrue(any(e["kind"] == "tool" for e in p["events"]))


class TestCoreChecks(unittest.TestCase):
    """Core is hypothesis-AGNOSTIC — exercised with a benchmark that is NOT
    app-discovery, so it proves genericity rather than coincidence."""
    def setUp(self):
        self.c = grade.process_checks(grade.parse_transcript(GENERIC), NEUTRAL_GT)

    def test_only_core_signals_present(self):
        self.assertEqual(set(self.c), {"read_agent_docs", "exploration_breadth",
                                       "emitted_expected_answers", "stayed_read_only"})

    def test_read_agent_docs(self):
        self.assertTrue(self.c["read_agent_docs"])

    def test_breadth_counts_distinct_reads(self):
        self.assertEqual(self.c["exploration_breadth"], 3)  # README, config.yaml, the grep

    def test_stayed_read_only_defaults_true(self):
        self.assertTrue(self.c["stayed_read_only"])


class TestEmittedExpectedAnswers(unittest.TestCase):
    """Derived from the ground-truth's OWN keys — proven with arbitrary field
    names, not the app-discovery five."""
    def test_true_when_final_mentions_all_gt_keys(self):
        c = grade.process_checks(grade.parse_transcript(GENERIC), NEUTRAL_GT)
        self.assertTrue(c["emitted_expected_answers"])

    def test_false_when_a_gt_key_is_missing_from_final(self):
        gt2 = {**NEUTRAL_GT, "tls_mode": ""}  # a key the ANSWER block never mentions
        c = grade.process_checks(grade.parse_transcript(GENERIC), gt2)
        self.assertFalse(c["emitted_expected_answers"])

    def test_answer_keys_are_gt_keys_minus_metadata(self):
        self.assertEqual(grade.answer_keys(NEUTRAL_GT),
                         ["widget_engine", "listen_port", "color_scheme"])

    def test_omitted_when_no_answer_keys(self):
        # task-completion-style GT (no answer fields) -> signal is omitted, not a false no-op
        c = grade.process_checks(grade.parse_transcript(GENERIC), {"app": "x", "vulns": []})
        self.assertNotIn("emitted_expected_answers", c)


class TestCustomChecks(unittest.TestCase):
    """A benchmark's hypothesis-specific signals live in ITS checks.py. The
    app-discovery signals (docs-before-conclusion, legacy-menu) are exactly such
    a plugin — so THIS is the only place the discovery fixtures are used."""
    DISCOVERY_GT = {"app": "d", "run_command": "", "host": "", "api_style": "",
                    "spa": "", "auth": "", "evidence": {}}
    CHECKS_PY = '''
import re
CONCL = re.compile(r"DISCOVERY:|api_style:|host:\\s*http", re.I)
DOC = re.compile(r"README|CLAUDE\\.md|AGENTS\\.md", re.I)
LEGACY = re.compile(r"node -e .*(react|vue|spa)|@PreAuthorize|AddAuthentication\\(", re.I)

def checks(parsed, ground_truth):
    first_doc = first_concl = None
    for i, e in enumerate(parsed.get("events", [])):
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

    def test_pigeonhole_flagged(self):
        out = self.fn(grade.parse_transcript(FX / "transcript_pigeonhole.jsonl"), self.DISCOVERY_GT)
        self.assertFalse(out["docs_before_conclusion"])

    def test_docs_first_passes(self):
        out = self.fn(grade.parse_transcript(FX / "transcript_new.jsonl"), self.DISCOVERY_GT)
        self.assertTrue(out["docs_before_conclusion"])

    def test_legacy_menu_detected_on_old_arm_only(self):
        self.assertTrue(self.fn(grade.parse_transcript(FX / "transcript_old.jsonl"), self.DISCOVERY_GT)["ran_legacy_command_menu"])
        self.assertFalse(self.fn(grade.parse_transcript(FX / "transcript_new.jsonl"), self.DISCOVERY_GT)["ran_legacy_command_menu"])


class TestGradeCliMerge(unittest.TestCase):
    """End-to-end via the grade.py CLI (--no-judge), on the NEUTRAL benchmark:
    the checks.py merge, fail-safe degradation, and core-wins-on-collision."""
    def _run(self, checks_py_body):
        cell = pathlib.Path(tempfile.mkdtemp())
        shutil.copy(GENERIC, cell / "transcript.jsonl")
        (cell / "gt.json").write_text(json.dumps(NEUTRAL_GT))
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
        self.assertIn("read_agent_docs", c)

    def test_raising_checks_degrades_to_core_without_aborting(self):
        p, c = self._run("def checks(p, g):\n    raise RuntimeError('boom')\n")
        self.assertEqual(p.returncode, 0)
        self.assertIn("read_agent_docs", c)
        self.assertNotIn("my_extra_signal", c)
        self.assertIn("custom checks.py failed", p.stderr)

    def test_core_wins_on_name_collision(self):
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
    def test_correctness_fields_derive_from_gt_keys(self):
        pr = grade.build_judge_prompt("final", "excerpt", NEUTRAL_GT)
        self.assertIn("exploratory_score", pr)
        # the arbitrary GT keys appear as the correctness fields — not a fixed list
        self.assertIn("widget_engine", pr)
        self.assertIn("listen_port", pr)
        self.assertNotIn("run_command", pr)


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
