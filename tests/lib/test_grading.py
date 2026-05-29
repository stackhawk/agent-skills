# tests/lib/test_grading.py
from evals.lib.models import ParsedRun, PromptConfig, BudgetSpec, ExpectedCheck, Verdict
from evals.lib.grading import (
    applicable_checks, run_process_checks, run_adhoc_expected, check_budget, grade,
)


def _prompt(**kw):
    base = dict(id="d-01", should_trigger=True, invocation_type="explicit", prompt="x")
    base.update(kw)
    return PromptConfig(**base)


def test_applicable_checks_global_and_scoped():
    checks = [
        {"id": "global", "type": "command_executed", "signals": ["a"], "severity": "warning"},
        {"id": "scoped", "type": "command_executed", "signals": ["b"], "severity": "warning",
         "applies_to": ["d-02"]},
    ]
    assert {c["id"] for c in applicable_checks(checks, "d-01")} == {"global"}
    assert {c["id"] for c in applicable_checks(checks, "d-02")} == {"global", "scoped"}


def test_process_check_signal_hit():
    run = ParsedRun(bash_commands=["hawk scan --env test"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    res = run_process_checks(run, checks)
    assert res[0].passed is True
    assert res[0].signal_found == "hawk scan"


def test_process_check_anti_pattern_negative_type():
    run = ParsedRun(bash_commands=["curl https://api/v1/scan"])
    checks = [{"id": "c1", "type": "command_negative", "anti_patterns": ["curl"],
               "severity": "warning"}]
    res = run_process_checks(run, checks)
    assert res[0].passed is False
    assert res[0].anti_found == "curl"


def test_adhoc_expected_signal_and_anti():
    run = ParsedRun(bash_commands=["hawk validate"], output_text="done")
    expected = [ExpectedCheck(signal="hawk validate"),
                ExpectedCheck(anti_pattern="rm -rf")]
    res = run_adhoc_expected(run, expected)
    assert all(r.passed for r in res)


def test_adhoc_expected_missing_signal_is_blocking_fail():
    run = ParsedRun(bash_commands=["hawk scan"])
    res = run_adhoc_expected(run, [ExpectedCheck(signal="hawk validate")])
    assert res[0].passed is False
    assert res[0].severity == "blocking"


def test_check_budget_detects_breaches():
    run = ParsedRun(bash_commands=["a", "b", "c"], cost_usd=0.30, output_tokens=9000)
    budget = BudgetSpec(cost_usd=0.15, bash_commands=2, output_tokens=5000)
    breaches = check_budget(run, budget)
    assert any("cost_usd" in b for b in breaches)
    assert any("bash_commands" in b for b in breaches)
    assert any("output_tokens" in b for b in breaches)


def test_check_budget_ignores_unset_axes():
    run = ParsedRun(bash_commands=["a", "b", "c"])
    assert check_budget(run, BudgetSpec(cost_usd=1.0)) == []


def test_grade_pass():
    run = ParsedRun(bash_commands=["hawk scan"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    result = grade(_prompt(), run, checks, platform="claude-code", skill="demo",
                   did_trigger=True)
    assert result.verdict == Verdict.PASS
    assert result.score == 100


def test_grade_fail_on_blocking():
    run = ParsedRun(bash_commands=["echo nope"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    result = grade(_prompt(), run, checks, platform="claude-code", skill="demo",
                   did_trigger=True)
    assert result.verdict == Verdict.FAIL


def test_grade_pass_slow_on_budget_breach():
    run = ParsedRun(bash_commands=["hawk scan", "a", "b", "c"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    p = _prompt(budget=BudgetSpec(bash_commands=2))
    result = grade(p, run, checks, platform="claude-code", skill="demo",
                   did_trigger=True)
    assert result.verdict == Verdict.PASS_SLOW
    assert any("bash_commands" in b for b in result.budget_breaches)
