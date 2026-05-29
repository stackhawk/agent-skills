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
