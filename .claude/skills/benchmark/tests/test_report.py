import json, pathlib, tempfile, unittest, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import report

def _cell(root, arm, app, checks, grade):
    d = root / "cells" / f"{arm}__{app}"; d.mkdir(parents=True)
    (d/"checks.json").write_text(json.dumps(checks)); (d/"grade.json").write_text(json.dumps(grade))

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        base_checks = {"read_agent_docs":True,"docs_before_conclusion":True,"explored_manifests":True,
                       "exploration_breadth":6,"emitted_five_answers":True,"stayed_read_only":True,"ran_legacy_command_menu":False}
        old_checks = {**base_checks,"read_agent_docs":False,"docs_before_conclusion":False,"exploration_breadth":2,"ran_legacy_command_menu":True}
        good = {"exploratory_score":3,"pigeonholed":False,"correctness":{"host":"correct"}}
        bad  = {"exploratory_score":1,"pigeonholed":True,"correctness":{"host":"wrong"}}
        _cell(self.tmp,"new","miniflux",base_checks,good)
        _cell(self.tmp,"old","miniflux",old_checks,bad)

    def test_aggregate_pairs_arms(self):
        agg = report.aggregate(self.tmp)
        self.assertIn("miniflux", agg["apps"])
        self.assertEqual(agg["apps"]["miniflux"]["new"]["exploration_breadth"], 6)
        self.assertEqual(agg["apps"]["miniflux"]["old"]["exploration_breadth"], 2)

    def test_means_show_new_better(self):
        agg = report.aggregate(self.tmp)
        self.assertGreater(agg["means"]["new"]["exploration_breadth"], agg["means"]["old"]["exploration_breadth"])
        self.assertGreater(agg["means"]["new"]["read_agent_docs_rate"], agg["means"]["old"]["read_agent_docs_rate"])

    def test_render_markdown_has_table(self):
        md = report.render_markdown(report.aggregate(self.tmp))
        self.assertIn("| miniflux", md); self.assertIn("OLD", md); self.assertIn("NEW", md)

class TestTaskCompletion(unittest.TestCase):
    def test_task_completion_means(self):
        import report, json, tempfile, pathlib
        tmp = pathlib.Path(tempfile.mkdtemp())
        for arm, cr in (("old",0.5),("new",1.0)):
            d = tmp/"cells"/f"{arm}__vampi"; d.mkdir(parents=True)
            (d/"checks.json").write_text("{}")
            (d/"grade.json").write_text(json.dumps({"close_rate":cr,"coverage_not_reduced":True,"app_not_broken":True}))
        agg = report.aggregate(tmp)
        self.assertGreater(agg["means"]["new"]["close_rate"], agg["means"]["old"]["close_rate"])
        md = report.render_markdown(agg); self.assertIn("close_rate", md)
