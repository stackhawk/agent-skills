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


def test_write_github_summary_appends(tmp_path, monkeypatch):
    from evals.lib.reporting import write_github_summary
    f = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
    write_github_summary("## hello\n")
    assert "## hello" in f.read_text()


def test_write_github_summary_noop_when_unset(monkeypatch):
    from evals.lib.reporting import write_github_summary
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_github_summary("nothing")   # must not raise


def test_render_digest_overview_and_per_cell():
    from pathlib import Path
    from evals.lib.models import CellReport
    from evals.lib.reporting import render_digest
    root = Path(__file__).parent.parent / "fixtures" / "results"
    cells = [CellReport.model_validate_json((p / "cell.json").read_text())
             for p in sorted(root.iterdir()) if (p / "cell.json").exists()]
    md = render_digest(cells)
    assert "Skill Eval" in md
    assert "claude-code" in md and "codex" in md
    assert "hw-14" in md            # failing test surfaced
    assert "no baseline" in md.lower()   # no baseline supplied
