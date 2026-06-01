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


def test_process_check_conditional_command_enforced_when_keyword_present():
    run = ParsedRun(bash_commands=["cat stackhawk.yml: authentication: enabled"],
                    output_text="hawk validate ran")
    checks = [{"id": "c1", "type": "conditional_command",
               "condition": "stackhawk.yml contains 'authentication:'",
               "signals": ["hawk validate"], "severity": "warning"}]
    assert run_process_checks(run, checks)[0].passed is True


def test_process_check_conditional_command_skipped_when_keyword_absent():
    run = ParsedRun(bash_commands=["echo nothing relevant"])
    checks = [{"id": "c1", "type": "conditional_command",
               "condition": "stackhawk.yml contains 'authentication:'",
               "signals": ["hawk validate"], "severity": "warning"}]
    # keyword not in haystack -> check is not applicable -> passes
    assert run_process_checks(run, checks)[0].passed is True


def test_process_check_conditional_command_raises_without_quoted_keyword():
    import pytest
    run = ParsedRun(bash_commands=["x"])
    checks = [{"id": "c1", "type": "conditional_command",
               "condition": "no quotes here", "signals": ["x"], "severity": "warning"}]
    with pytest.raises(ValueError, match="single-quoted keyword"):
        run_process_checks(run, checks)


def test_process_check_command_preference_normal():
    run = ParsedRun(bash_commands=["hawkop scan get 123"])
    checks = [{"id": "c1", "type": "command_preference",
               "preferred": ["hawkop scan get"], "anti_patterns": ["curl"],
               "severity": "warning"}]
    assert run_process_checks(run, checks)[0].passed is True


def test_process_check_command_preference_empty_is_unconstrained():
    run = ParsedRun(bash_commands=["anything"])
    checks = [{"id": "c1", "type": "command_preference", "preferred": [],
               "anti_patterns": ["curl"], "severity": "warning"}]
    assert run_process_checks(run, checks)[0].passed is True


def test_process_check_file_absent():
    run = ParsedRun(files_written=["stackhawk.yml"])
    present = [{"id": "c1", "type": "file_absent", "target_file": "stackhawk.yml",
                "severity": "warning"}]
    absent = [{"id": "c2", "type": "file_absent", "target_file": "secrets.env",
               "severity": "warning"}]
    assert run_process_checks(run, present)[0].passed is False
    assert run_process_checks(run, absent)[0].passed is True


def test_adhoc_expected_check_id_is_skipped():
    run = ParsedRun(bash_commands=["x"])
    assert run_adhoc_expected(run, [ExpectedCheck(check_id="step1")]) == []


def test_score_deductions():
    from evals.lib.grading import _score
    from evals.lib.models import ProcessCheckResult
    def pc(passed, sev): return ProcessCheckResult(id="x", passed=passed, severity=sev)
    assert _score([pc(True, "blocking")]) == 100
    assert _score([pc(False, "blocking")]) == 85
    assert _score([pc(False, "warning")]) == 95
    assert _score([pc(False, "blocking"), pc(False, "warning")]) == 80
    assert _score([pc(False, "blocking")] * 8) == 0  # floored


def test_grade_correct_negative_passes_without_process_checks():
    # should_trigger=False, did_trigger=False -> correct -> PASS, no process checks run
    run = ParsedRun(bash_commands=["echo not relevant"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    p = _prompt(should_trigger=False)
    res = grade(p, run, checks, platform="claude-code", skill="demo", did_trigger=False)
    assert res.verdict == Verdict.PASS
    assert res.trigger_correct is True
    assert res.process_checks == []
    assert res.score == 100


def test_grade_false_negative_fails():
    # should_trigger=True but did_trigger=False -> incorrect -> FAIL, no process checks
    run = ParsedRun(bash_commands=["echo nothing"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    p = _prompt(should_trigger=True)
    res = grade(p, run, checks, platform="claude-code", skill="demo", did_trigger=False)
    assert res.verdict == Verdict.FAIL
    assert res.trigger_correct is False
    assert res.process_checks == []


def test_grade_false_positive_fails_without_process_checks():
    # should_trigger=False but did_trigger=True -> incorrect -> FAIL, no process checks
    run = ParsedRun(bash_commands=["hawk scan"])
    checks = [{"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
               "severity": "blocking"}]
    p = _prompt(should_trigger=False)
    res = grade(p, run, checks, platform="claude-code", skill="demo", did_trigger=True)
    assert res.verdict == Verdict.FAIL
    assert res.trigger_correct is False
    assert res.process_checks == []


def test_grade_propagates_harness_error_to_note():
    from evals.lib.models import ParsedRun, Verdict
    from evals.lib.grading import grade
    p = _prompt(should_trigger=True)   # _prompt helper already in this file
    run = ParsedRun(returncode=1, stderr_tail="agent: command not found", error="exit 1: agent: command not found")
    res = grade(p, run, [], platform="cursor", skill="hawkscan", did_trigger=False)
    assert res.verdict == Verdict.FAIL          # didn't trigger
    assert "command not found" in res.note      # harness error surfaced
