from pathlib import Path

from evals.lib.models import EvalResult, Verdict, RubricResult
from evals.lib.reporting import _pivot_cell
from evals.lib.rubric import grade_rubric
from evals.lib.models import ParsedRun


def _res(rubric=None, verdict=Verdict.PASS):
    return EvalResult(platform="claude-code", skill="hawkscan", run_id="hw-01",
                      should_trigger=True, did_trigger=True, trigger_correct=True,
                      verdict=verdict, score=100, rubric=rubric)


def test_pivot_cell_omits_rubric_tag():
    # The rubric is extended-only and surfaced separately — it must NOT be woven
    # into the pivot cell as a cryptic code (r85✓ / r55✗ / r?). Cells stay glanceable.
    assert _pivot_cell(_res(RubricResult(overall_pass=True, score=85))) == "✅"
    assert _pivot_cell(_res(RubricResult(overall_pass=False, score=55))) == "✅"
    assert _pivot_cell(_res(None)) == "✅"
    assert _pivot_cell(_res(RubricResult(overall_pass=False, score=0, error="x"))) == "✅"


def test_grade_rubric_none_when_config_missing(tmp_path: Path):
    # no rubric-items.json / rubric-schema.json under base_dir -> None (not an error)
    assert grade_rubric(ParsedRun(output_text="x"), "hawkscan", "hw-01",
                        base_dir=tmp_path) is None
