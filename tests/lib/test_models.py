# tests/lib/test_models.py
import pytest
from pydantic import ValidationError
from evals.lib.models import (
    BudgetSpec, ExpectedCheck, PromptConfig, ParsedRun, Verdict,
)


def test_prompt_config_minimal():
    p = PromptConfig(id="hw-01", should_trigger=True,
                     invocation_type="explicit", prompt="scan it")
    assert p.budget is None
    assert p.expected == []
    assert p.notes == ""


def test_prompt_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PromptConfig(id="hw-01", should_trigger=True,
                     invocation_type="explicit", prompt="x", budget_usd=0.1)


def test_budget_spec_rejects_unknown_axis():
    with pytest.raises(ValidationError):
        BudgetSpec(cost_dollars=0.1)


def test_expected_check_requires_exactly_one():
    ExpectedCheck(signal="hawk scan")            # ok
    ExpectedCheck(check_id="step1")              # ok
    ExpectedCheck(anti_pattern="curl")           # ok
    with pytest.raises(ValidationError):
        ExpectedCheck()                          # none set
    with pytest.raises(ValidationError):
        ExpectedCheck(signal="a", anti_pattern="b")  # two set


def test_invocation_type_is_constrained():
    with pytest.raises(ValidationError):
        PromptConfig(id="x", should_trigger=True,
                     invocation_type="bogus", prompt="x")


def test_verdict_values():
    assert Verdict.PASS == "pass"
    assert Verdict.PASS_SLOW == "pass-slow"
    assert Verdict.FAIL == "fail"


def test_parsed_run_defaults():
    r = ParsedRun()
    assert r.bash_commands == []
    assert r.cost_usd == 0.0
    assert r.output_tokens is None


def test_cellreport_roundtrips():
    from evals.lib.models import CellReport, EvalResult, Verdict
    r = EvalResult(platform="codex", skill="hawkscan", run_id="hw-01",
                   should_trigger=True, did_trigger=True, trigger_correct=True,
                   verdict=Verdict.PASS, score=100)
    cell = CellReport(platform="codex", skill="hawkscan", model="haiku",
                      commit="abc1234", results=[r])
    again = CellReport.model_validate_json(cell.model_dump_json())
    assert again.results[0].run_id == "hw-01"
    assert again.model == "haiku"


def test_cellreport_rejects_unknown_field():
    import pytest
    from pydantic import ValidationError
    from evals.lib.models import CellReport
    with pytest.raises(ValidationError):
        CellReport(platform="x", skill="y", model="m", commit="c", results=[], extra=1)


def test_parsedrun_has_diagnostic_fields():
    from evals.lib.models import ParsedRun
    r = ParsedRun()
    assert r.returncode is None
    assert r.stderr_tail == ""
    r2 = ParsedRun(returncode=1, stderr_tail="boom")
    assert r2.returncode == 1 and r2.stderr_tail == "boom"


def test_evalresult_has_note_field():
    from evals.lib.models import EvalResult, Verdict
    e = EvalResult(platform="p", skill="s", run_id="r", should_trigger=True,
                   did_trigger=True, trigger_correct=True, verdict=Verdict.PASS, score=100)
    assert e.note == ""
    e2 = EvalResult(platform="p", skill="s", run_id="r", should_trigger=True,
                    did_trigger=False, trigger_correct=False, verdict=Verdict.FAIL,
                    score=0, note="harness error: agent: command not found")
    assert "command not found" in e2.note
