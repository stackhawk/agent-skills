"""Grading: process checks (ported from the claude-code harness), per-prompt
ad-hoc expectations, budget scoring, and the three-state verdict."""
from __future__ import annotations
import re

from evals.lib.models import (
    ParsedRun, PromptConfig, BudgetSpec, ExpectedCheck, Verdict,
    ProcessCheckResult, EvalResult,
)


def applicable_checks(checks: list[dict], prompt_id: str) -> list[dict]:
    """A check applies if it has no applies_to (global) or names this prompt id."""
    out = []
    for c in checks:
        targets = c.get("applies_to")
        if not targets or prompt_id in targets:
            out.append(c)
    return out


def _haystack(run: ParsedRun) -> str:
    return " ".join([*run.bash_commands, run.output_text]).lower()


def run_process_checks(run: ParsedRun, checks: list[dict]) -> list[ProcessCheckResult]:
    haystack = _haystack(run)
    all_files = " ".join(run.files_written + run.files_edited).lower()
    results: list[ProcessCheckResult] = []

    for check in checks:
        ctype = check.get("type", "command_executed")
        signals = [s.lower() for s in check.get("signals", [])]
        antis = [a.lower() for a in check.get("anti_patterns", [])]
        signal_hit = next((s for s in signals if s in haystack), None)
        anti_hit = next((a for a in antis if a in haystack), None)

        if ctype in ("command_negative", "file_content_negative", "output_negative"):
            passed = anti_hit is None
        elif ctype == "file_absent":
            target = check.get("target_file", "").lower()
            passed = target not in all_files
        elif ctype == "conditional_command":
            condition_str = check.get("condition", "")
            m = re.search(r"'([^']+)'", condition_str)
            if condition_str and m is None:
                raise ValueError(
                    f"conditional_command check '{check['id']}': condition "
                    f"'{condition_str}' has no single-quoted keyword")
            keyword = m.group(1).lower() if m else None
            passed = True if (keyword and keyword not in haystack) else signal_hit is not None
        elif ctype == "command_preference":
            preferred = [p.lower() for p in check.get("preferred", [])]
            if preferred:
                passed = any(p in haystack for p in preferred) and anti_hit is None
            else:
                passed = anti_hit is None  # no preference expressed; only anti-patterns matter
        else:
            passed = signal_hit is not None and (anti_hit is None if antis else True)

        results.append(ProcessCheckResult(
            id=check["id"], passed=passed,
            severity=check.get("severity", "warning"),
            signal_found=signal_hit, anti_found=anti_hit,
        ))
    return results


def run_adhoc_expected(run: ParsedRun, expected: list[ExpectedCheck]) -> list[ProcessCheckResult]:
    """Per-prompt expectations. signal/anti_pattern are blocking; check_id refs are
    resolved by the caller against process-checks and skipped here."""
    haystack = _haystack(run)
    results: list[ProcessCheckResult] = []
    for i, exp in enumerate(expected):
        if exp.check_id is not None:
            continue  # handled via applies_to / process checks
        if exp.signal is not None:
            hit = exp.signal.lower() in haystack
            results.append(ProcessCheckResult(
                id=f"expected[{i}]:signal", passed=hit, severity="blocking",
                signal_found=exp.signal if hit else None))
        elif exp.anti_pattern is not None:
            hit = exp.anti_pattern.lower() in haystack
            results.append(ProcessCheckResult(
                id=f"expected[{i}]:anti", passed=not hit, severity="blocking",
                anti_found=exp.anti_pattern if hit else None))
    return results


def check_budget(run: ParsedRun, budget: BudgetSpec) -> list[str]:
    breaches: list[str] = []
    if budget.cost_usd is not None and run.cost_usd > budget.cost_usd:
        breaches.append(f"cost_usd {run.cost_usd:.3f} > {budget.cost_usd:.3f}")
    if budget.bash_commands is not None and len(run.bash_commands) > budget.bash_commands:
        breaches.append(f"bash_commands {len(run.bash_commands)} > {budget.bash_commands}")
    if budget.output_tokens is not None and (run.output_tokens or 0) > budget.output_tokens:
        breaches.append(f"output_tokens {run.output_tokens} > {budget.output_tokens}")
    if budget.wall_seconds is not None and (run.wall_seconds or 0) > budget.wall_seconds:
        breaches.append(f"wall_seconds {run.wall_seconds:.0f} > {budget.wall_seconds:.0f}")
    return breaches


def _score(checks: list[ProcessCheckResult]) -> int:
    blocking = sum(1 for c in checks if not c.passed and c.severity == "blocking")
    warning = sum(1 for c in checks if not c.passed and c.severity == "warning")
    return max(0, 100 - blocking * 15 - warning * 5)


def grade(prompt: PromptConfig, run: ParsedRun, checks: list[dict], *,
          platform: str, skill: str, did_trigger: bool) -> EvalResult:
    trigger_correct = (did_trigger == prompt.should_trigger)

    # Process checks, ad-hoc expectations, and budgets only apply when the skill
    # should have fired AND did. For correct non-triggers, false positives, and
    # false negatives, the verdict is purely the trigger outcome (no process grading).
    if not (prompt.should_trigger and did_trigger):
        return EvalResult(
            platform=platform, skill=skill, run_id=prompt.id,
            should_trigger=prompt.should_trigger, did_trigger=did_trigger,
            trigger_correct=trigger_correct,
            verdict=Verdict.PASS if trigger_correct else Verdict.FAIL,
            budget_breaches=[], process_checks=[],
            score=100 if trigger_correct else 0, cost_usd=run.cost_usd,
        )

    proc = run_process_checks(run, applicable_checks(checks, prompt.id))
    proc += run_adhoc_expected(run, prompt.expected)

    blocking_failed = any(not c.passed and c.severity == "blocking" for c in proc)
    verdict = Verdict.FAIL if blocking_failed else Verdict.PASS

    breaches: list[str] = []
    if verdict == Verdict.PASS and prompt.budget is not None:
        breaches = check_budget(run, prompt.budget)
        if breaches:
            verdict = Verdict.PASS_SLOW

    return EvalResult(
        platform=platform, skill=skill, run_id=prompt.id,
        should_trigger=prompt.should_trigger, did_trigger=did_trigger,
        trigger_correct=trigger_correct,
        verdict=verdict, budget_breaches=breaches, process_checks=proc,
        score=_score(proc), cost_usd=run.cost_usd,
    )
