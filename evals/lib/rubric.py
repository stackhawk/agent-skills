"""Qualitative, model-assisted rubric grader.

Ported from origin/main's `--rubric` pass (evals/harnesses/*/run-evals.py).
A grader model (claude) reviews an agent run's transcript against the skill's
rubric-items.json and returns a structured 0-100 quality score + per-item
pass/fail. This is the QUALITATIVE axis that complements the deterministic
process-checks, and it's woven into the pass/fail table by the reporter.

The grader judges text only, so it is platform-independent: every harness's
transcript is graded by the same claude grader. Requires ANTHROPIC_API_KEY.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from evals.lib.models import ParsedRun, RubricResult, RubricCheckResult

EVALS_DIR = Path(__file__).resolve().parent.parent  # repo/evals


def _build_prompt(rubric_data: dict, run: ParsedRun, skill: str, run_id: str) -> str:
    return f"""{rubric_data['grader_prompt']}

## Bash Commands Executed:
{json.dumps(run.bash_commands, indent=2)}

## Files Written/Edited:
{json.dumps(run.files_written + run.files_edited, indent=2)}

## Agent Output (first 4000 chars):
{run.output_text[:4000]}

## Rubric Checks to Grade:
{json.dumps(rubric_data['checks'], indent=2)}

Populate the JSON result with:
  skill = "{skill}"
  run_id = "{run_id}"
  overall_pass = true if all checks pass and score >= 70
  score = 0-100 (each failed check deducts: blocking 15, warning 5)
  checks = one entry per check id listed above"""


# Cheap, capable grader by default — judging a transcript against a rubric is a
# structured classification task. Budget must cover the full prompt (transcript +
# rubric + schema); 0.10 hit error_max_budget_usd, so use a roomier cap.
DEFAULT_GRADER_MODEL = "claude-haiku-4-5-20251001"
GRADER_BUDGET_USD = "0.25"


def grade_rubric(run: ParsedRun, skill: str, run_id: str, *,
                 grader_model: str | None = None, timeout: int = 120,
                 base_dir: Path | None = None) -> RubricResult | None:
    """Run the qualitative grader. Returns a RubricResult, or None if the rubric
    config is absent. On grader failure returns a RubricResult with error set so
    the run still records a (failed) rubric cell rather than silently dropping it."""
    base = base_dir or EVALS_DIR
    rubric_path = base / skill / "rubric-items.json"
    schema_path = base / "rubric-schema.json"
    if not rubric_path.exists() or not schema_path.exists():
        return None
    rubric_data = json.loads(rubric_path.read_text())
    schema = json.loads(schema_path.read_text())

    # NOTE: no --bare here. --bare ("minimal mode") suppresses the structured
    # --json-schema output (returns an empty result), so the grader must run in
    # full mode. It's a one-shot text judge; no plugin-dir needed.
    cmd = ["claude", "-p", _build_prompt(rubric_data, run, skill, run_id),
           "--output-format", "json", "--no-session-persistence",
           "--json-schema", json.dumps(schema),
           "--max-budget-usd", GRADER_BUDGET_USD,
           "--model", grader_model or DEFAULT_GRADER_MODEL]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        envelope = json.loads(proc.stdout)
        # --output-format json wraps as {"result": "<json|obj>", ...}; some modes
        # return the schema object directly. Handle both.
        raw = envelope.get("result", envelope) if isinstance(envelope, dict) else envelope
        result = raw if isinstance(raw, dict) else json.loads(raw)
        if "score" not in result and "overall_pass" not in result:
            raise ValueError(f"grader returned no rubric fields: {str(result)[:120]}")
    except Exception as exc:  # noqa: BLE001 — grader is best-effort
        return RubricResult(overall_pass=False, score=0, checks=[],
                            error=f"grader failed: {type(exc).__name__}: {exc}")

    checks = [RubricCheckResult(id=c.get("id", "?"), passed=bool(c.get("pass")),
                                notes=c.get("notes", ""))
              for c in result.get("checks", [])]
    return RubricResult(overall_pass=bool(result.get("overall_pass")),
                        score=int(result.get("score", 0)), checks=checks)
