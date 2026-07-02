import json, pathlib, tempfile, unittest, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import report


def _cell(root, arm, app, checks, grade=None):
    d = root / "cells" / f"{arm}__{app}"
    d.mkdir(parents=True)
    (d / "checks.json").write_text(json.dumps(checks))
    if grade is not None:
        (d / "grade.json").write_text(json.dumps(grade))


class TestDynamicSignals(unittest.TestCase):
    """report.py renders whatever signals the benchmark emitted — including an
    arbitrary custom signal it has never heard of."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        core = {"read_agent_docs": False, "exploration_breadth": 2, "my_custom_signal": False}
        _cell(self.tmp, "old", "app1", {**core},
              {"correctness": {"a": "wrong"}, "exploratory_score": 2, "pigeonholed": True})
        _cell(self.tmp, "new", "app1",
              {"read_agent_docs": True, "exploration_breadth": 6, "my_custom_signal": True},
              {"correctness": {"a": "correct"}, "exploratory_score": 3, "pigeonholed": False})

    def test_arbitrary_signal_surfaces(self):
        agg = report.aggregate(self.tmp)
        self.assertIn("my_custom_signal", agg["signal_keys"])
        self.assertEqual(agg["means"]["new"]["my_custom_signal_rate"], 1.0)

    def test_numeric_signal_meaned_bool_signal_rated(self):
        agg = report.aggregate(self.tmp)
        self.assertGreater(agg["means"]["new"]["exploration_breadth"],
                           agg["means"]["old"]["exploration_breadth"])
        self.assertEqual(agg["means"]["new"]["read_agent_docs_rate"], 1.0)
        self.assertEqual(agg["means"]["old"]["read_agent_docs_rate"], 0.0)

    def test_judge_metrics_aggregated(self):
        agg = report.aggregate(self.tmp)
        self.assertEqual(agg["means"]["new"]["answers_correct"], 1)
        self.assertEqual(agg["means"]["old"]["pigeonholed_rate"], 1.0)

    def test_render_includes_custom_signal_column(self):
        md = report.render_markdown(report.aggregate(self.tmp))
        self.assertIn("my_custom_signal", md)
        self.assertIn("| app1 |", md)
        self.assertIn("OLD", md)
        self.assertIn("NEW", md)


class TestTaskCompletion(unittest.TestCase):
    def test_task_completion_means(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        _cell(tmp, "old", "vampi", {"stayed_read_only": True},
              {"close_rate": 0.5, "coverage_not_reduced": True, "app_not_broken": True})
        _cell(tmp, "new", "vampi", {"stayed_read_only": True},
              {"close_rate": 1.0, "coverage_not_reduced": True, "app_not_broken": True})
        agg = report.aggregate(tmp)
        self.assertGreater(agg["means"]["new"]["close_rate"], agg["means"]["old"]["close_rate"])
        self.assertIn("close_rate", report.render_markdown(agg))


class TestMissingCellTolerated(unittest.TestCase):
    def test_no_grade_json_does_not_crash(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        _cell(tmp, "old", "a", {"read_agent_docs": True})  # no grade.json
        _cell(tmp, "new", "a", {"read_agent_docs": True})
        md = report.render_markdown(report.aggregate(tmp))
        self.assertIn("read_agent_docs", md)


if __name__ == "__main__":
    unittest.main()
