"""Pydantic data contracts for the eval system. extra='forbid' makes config
typos hard load-time errors instead of silently-ignored fields."""
from __future__ import annotations
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class BudgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost_usd: float | None = None
    bash_commands: int | None = None
    output_tokens: int | None = None
    wall_seconds: float | None = None


class TargetRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str            # e.g. https://github.com/stackhawk-research/firefly-iii.git
    pin: str            # commit SHA (mirrors carry no release tags)


class ExpectedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str | None = None      # reference an existing process-check by id
    signal: str | None = None        # ad-hoc substring that MUST appear
    anti_pattern: str | None = None  # substring that must NOT appear

    @model_validator(mode="after")
    def _exactly_one(self) -> "ExpectedCheck":
        set_count = sum(x is not None for x in (self.check_id, self.signal, self.anti_pattern))
        if set_count != 1:
            raise ValueError("ExpectedCheck must set exactly one of "
                             "check_id / signal / anti_pattern")
        return self


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    should_trigger: bool
    invocation_type: Literal["explicit", "implicit", "contextual", "negative"]
    prompt: str
    notes: str = ""
    budget: BudgetSpec | None = None
    expected: list[ExpectedCheck] = []
    target_repo: TargetRepo | None = None      # clone into the cell cwd (read-only run)
    answer_key: str | None = None              # path, relative to the suite dir


class Verdict(str, Enum):
    PASS = "pass"
    PASS_SLOW = "pass-slow"
    FAIL = "fail"


class ParsedRun(BaseModel):
    bash_commands: list[str] = []
    files_written: list[str] = []
    files_edited: list[str] = []
    output_text: str = ""
    cost_usd: float = 0.0
    output_tokens: int | None = None
    wall_seconds: float | None = None
    error: str | None = None
    returncode: int | None = None
    stderr_tail: str = ""
    guard_denials: list[str] = []


class ProcessCheckResult(BaseModel):
    id: str
    passed: bool
    severity: Literal["blocking", "warning"]
    signal_found: str | None = None
    anti_found: str | None = None


class RubricCheckResult(BaseModel):
    id: str
    passed: bool
    notes: str = ""


class RubricResult(BaseModel):
    """Qualitative, model-graded result (ported from origin/main's --rubric pass).
    A grader model reviews the transcript against rubric-items.json and returns
    a 0-100 score + per-item pass/fail; overall_pass = all pass and score >= 70."""
    overall_pass: bool
    score: int
    checks: list[RubricCheckResult] = []
    error: str | None = None   # set if the grader couldn't run/parse


class EvalResult(BaseModel):
    platform: str
    skill: str
    run_id: str
    should_trigger: bool
    did_trigger: bool
    trigger_correct: bool
    verdict: Verdict
    budget_breaches: list[str] = []
    process_checks: list[ProcessCheckResult] = []
    score: int
    cost_usd: float = 0.0
    note: str = ""
    rubric: RubricResult | None = None   # populated only when --rubric is set


class CellReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str
    skill: str
    model: str
    commit: str
    results: list[EvalResult]


class LiftRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    without_verdict: Verdict
    with_verdict: Verdict
    effect: Literal["lift", "regress", "none"]
