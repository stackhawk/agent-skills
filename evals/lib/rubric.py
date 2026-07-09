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
import re
import subprocess
from pathlib import Path

from evals.lib.models import ParsedRun, RubricResult, RubricCheckResult, ProcessCheckResult

EVALS_DIR = Path(__file__).resolve().parent.parent  # repo/evals


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object out of a grader reply that may be pure JSON, wrapped in
    a ```json fence, or embedded in prose (e.g. "No skills needed.\\n\\n```json
    {...}```"). Tries direct parse, then a fenced block, then the first balanced
    {...} object."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError(f"no JSON object in grader result: {text[:120]}")


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
# Sonnet, not haiku: the answer-key judge GATES discovery verdicts via must-hit
# factors, and haiku false-failed semantically-correct matches (e.g. "Rails 8.0
# Hotwire" vs "Rails 8.0 ... Hotwire"). A gating judge needs a reliable grader.
DEFAULT_GRADER_MODEL = "claude-sonnet-4-6"
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
        if not proc.stdout.strip():
            # claude produced nothing on stdout — surface the real cause (exit
            # code + stderr) instead of a misleading JSONDecodeError downstream.
            tail = (proc.stderr or "").strip()[-200:]
            raise ValueError(f"grader produced no output (exit {proc.returncode}): {tail}")
        envelope = json.loads(proc.stdout)
        # --output-format json wraps as {"result": "<json|obj>", ...}; some modes
        # return the schema object directly. Handle both.
        raw = envelope.get("result", envelope) if isinstance(envelope, dict) else envelope
        # `raw` may be a dict already, or a string that is pure JSON, or — even with
        # --json-schema — a model reply that wraps the JSON in prose / a ```json
        # fence. Extract the object tolerantly.
        result = raw if isinstance(raw, dict) else _extract_json_object(raw)
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


# ---------------------------------------------------------------------------
# Answer-key judge: scores an agent's DISCOVERY block against a per-repo
# answer key via a skill-blind claude call, producing per-factor process
# checks (must-hit factor -> blocking; soft factor -> warning).
# ---------------------------------------------------------------------------

MUST_HIT = {"technology", "api_style", "host"}
FACTORS = ["technology", "run_command", "host", "api_style", "spa", "auth"]


def parse_discovery_block(text: str) -> dict:
    """Extract the factor lines after the literal 'DISCOVERY:' marker."""
    out: dict[str, str] = {}
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().upper().startswith("DISCOVERY:")), None)
    if start is None:
        return out
    for ln in lines[start + 1:]:
        if ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        key = key.strip().lower()
        if key in FACTORS:
            out[key] = val.strip()
    return out


def _judge_factors(parsed: dict, key: dict, *, grader_model=None, timeout=120) -> dict:
    """Ask a skill-blind claude judge whether each parsed factor matches the key.
    Returns {factor: bool}. Uses --json-schema for a structured reply."""
    factors = key["factors"]
    ask = {f: {"expected": factors[f]["value"], "got": parsed.get(f, "(missing)")}
           for f in factors}
    schema = {"type": "object", "properties": {"factors": {"type": "object",
              "additionalProperties": {"type": "boolean"}}}, "required": ["factors"]}
    prompt = ("You are grading an app-discovery result. For each factor, decide if the "
              "agent's 'got' value is semantically correct given the 'expected' answer "
              "(ignore wording, focus on meaning; a missing or wrong value is false). "
              "Return JSON {\"factors\": {<factor>: true|false}}.\n\n" + json.dumps(ask, indent=2))
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--no-session-persistence",
           "--json-schema", json.dumps(schema), "--max-budget-usd", GRADER_BUDGET_USD,
           "--model", grader_model or DEFAULT_GRADER_MODEL]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    envelope = json.loads(proc.stdout)
    raw = envelope.get("result", envelope) if isinstance(envelope, dict) else envelope
    result = raw if isinstance(raw, dict) else _extract_json_object(raw)
    return {f: bool(v) for f, v in result.get("factors", {}).items()}


def judge_answer_key(run: ParsedRun, answer_key_path: str, *,
                     grader_model=None, timeout=120) -> list[ProcessCheckResult]:
    """Score each DISCOVERY factor against the answer key -> per-factor checks.
    must-hit factor -> blocking severity; soft factor -> warning."""
    key = json.loads(Path(answer_key_path).read_text())
    parsed = parse_discovery_block(run.output_text)
    verdicts = _judge_factors(parsed, key, grader_model=grader_model, timeout=timeout)
    out: list[ProcessCheckResult] = []
    for f, spec in key["factors"].items():
        passed = bool(verdicts.get(f, False))
        must = spec.get("must_hit", f in MUST_HIT)
        out.append(ProcessCheckResult(
            id=f"answer_key:{f}", passed=passed,
            severity="blocking" if must else "warning",
            signal_found=(parsed.get(f) if passed else None),
            anti_found=(f"expected≈{spec['value']!r} got {parsed.get(f, '(missing)')!r}"
                        if not passed else None),
        ))
    return out
