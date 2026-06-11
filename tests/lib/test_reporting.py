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


def test_rollup_cell_health():
    from evals.lib.reporting import _rollup_cell
    from evals.lib.models import CellReport, EvalResult, Verdict
    def res(rid, verdict, note=""):
        return EvalResult(platform="p", skill="s", run_id=rid, should_trigger=True,
                          did_trigger=True, trigger_correct=True, verdict=verdict,
                          score=100, note=note)
    allpass = CellReport(platform="claude-code", skill="api", model="m",
                         commit="x", results=[res("a", Verdict.PASS), res("b", Verdict.PASS)])
    assert _rollup_cell(allpass) == "🟢 2/2"
    mixed = CellReport(platform="p", skill="s", model="m", commit="x",
                       results=[res(str(i), Verdict.PASS) for i in range(9)] + [res("x", Verdict.FAIL)])
    assert _rollup_cell(mixed) == "🟡 9/10"
    bad = CellReport(platform="p", skill="s", model="m", commit="x",
                     results=[res("a", Verdict.FAIL), res("b", Verdict.PASS)])
    assert _rollup_cell(bad) == "🔴 1/2"
    # all prompts errored at the harness level (e.g. agy OAuth) → plumbing, not a result
    plumbing = CellReport(platform="agy", skill="s", model="m", commit="x",
                          results=[res("a", Verdict.FAIL, note="agy: no headless auth"),
                                   res("b", Verdict.FAIL, note="timeout")])
    assert _rollup_cell(plumbing) == "🚫"
    assert _rollup_cell(None) == "·"


def test_render_job_summary_fail_why_not_empty():
    # A correctly-triggered run whose blocking process check fails (verdict FAIL,
    # trigger_correct=True, no budget breach, no note) must NOT render a blank why.
    from evals.lib.reporting import render_job_summary
    from evals.lib.models import CellReport, EvalResult, Verdict
    r = EvalResult(platform="claude-code", skill="hawkscan", run_id="hw-04",
                   should_trigger=True, did_trigger=True, trigger_correct=True,
                   verdict=Verdict.FAIL, score=0)
    cell = CellReport(platform="claude-code", skill="hawkscan", model="m",
                      commit="x", results=[r])
    md = render_job_summary(cell)
    assert "| hw-04 | ❌ FAIL | blocking check failed |" in md
