# tests/lib/test_reporting.py
from evals.lib.models import EvalResult, Verdict
from evals.lib.reporting import build_summary


def _r(run_id, verdict, trigger_ok=True, should=True, did=True):
    return EvalResult(platform="claude-code", skill="hawkscan", run_id=run_id,
                      should_trigger=should, did_trigger=did, trigger_correct=trigger_ok,
                      verdict=verdict, score=100 if verdict != Verdict.FAIL else 40)


def test_build_summary_counts():
    results = [_r("hw-01", Verdict.PASS), _r("hw-02", Verdict.PASS_SLOW),
               _r("hw-03", Verdict.FAIL),
               _r("hw-13", Verdict.PASS, trigger_ok=False, should=False, did=True)]
    s = build_summary("hawkscan", "claude-code", results)
    assert s["trigger_accuracy"]["correct"] == 3
    assert s["trigger_accuracy"]["total"] == 4
    assert s["false_positives"] == ["hw-13"]
    assert s["verdict_counts"] == {"pass": 2, "pass-slow": 1, "fail": 1}
