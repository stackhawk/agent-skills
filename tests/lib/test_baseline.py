from evals.lib.models import CellReport, EvalResult, Verdict
from evals.lib.baseline import diff, score_delta


def _cell(verdicts: dict):
    results = [EvalResult(platform="p", skill="s", run_id=k, should_trigger=True,
                          did_trigger=True, trigger_correct=True, verdict=v, score=100)
               for k, v in verdicts.items()]
    return CellReport(platform="p", skill="s", model="m", commit="c", results=results)


def test_diff_statuses():
    base = _cell({"a": Verdict.PASS, "b": Verdict.FAIL, "c": Verdict.PASS, "d": Verdict.PASS})
    cur = _cell({"a": Verdict.FAIL, "b": Verdict.PASS, "c": Verdict.PASS, "e": Verdict.PASS})
    d = diff(cur, base)
    assert d["a"] == "regressed"
    assert d["b"] == "fixed"
    assert d["c"] == "same"
    assert d["e"] == "new"
    assert d["d"] == "dropped"


def test_diff_changed_non_fail():
    base = _cell({"a": Verdict.PASS})
    cur = _cell({"a": Verdict.PASS_SLOW})
    assert diff(cur, base)["a"] == "changed"


def test_score_delta_bands():
    assert score_delta(90, 88) == "no-change"
    assert score_delta(95, 88) == "better"
    assert score_delta(80, 88) == "worse"
