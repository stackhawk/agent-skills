from evals.lib.models import CellReport, EvalResult, Verdict
from evals.lib.reporting import badge, render_job_summary


def _cell(*results):
    return CellReport(platform="claude-code", skill="hawkscan", model="haiku",
                      commit="abc1234", results=list(results))


def _r(rid, verdict, trig=True, should=True, did=True, why=""):
    return EvalResult(platform="claude-code", skill="hawkscan", run_id=rid,
                      should_trigger=should, did_trigger=did, trigger_correct=trig,
                      verdict=verdict, score=100 if verdict != Verdict.FAIL else 40,
                      budget_breaches=[why] if (why and verdict == Verdict.PASS_SLOW) else [])


def test_badge_is_shields_image():
    md = badge("fail", "FAIL")
    assert md.startswith("![") and "img.shields.io/badge/" in md


def test_job_summary_has_counts_and_all_rows_failures_first():
    cell = _cell(_r("hw-01", Verdict.PASS), _r("hw-02", Verdict.PASS),
                 _r("hw-14", Verdict.FAIL, trig=False, should=False, did=True))
    md = render_job_summary(cell)
    assert "claude-code" in md and "hawkscan" in md and "haiku" in md
    assert "1 failed" in md.lower() or "❌ 1" in md
    for rid in ("hw-01", "hw-02", "hw-14"):
        assert rid in md
    # failing row appears before the first passing row
    assert md.index("hw-14") < md.index("hw-01")
