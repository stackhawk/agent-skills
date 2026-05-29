"""Regrade a saved trace with no agent call — the zero-cost iteration loop.
The trace filename stem is the prompt id (e.g. hw-07.trace.jsonl -> hw-07)."""
from __future__ import annotations
from pathlib import Path

from evals.lib.config import load_skill
from evals.lib.grading import grade
from evals.lib.harness import get_adapter
from evals.lib.models import EvalResult


def _prompt_id_from_path(trace_path: Path) -> str:
    return trace_path.name.split(".")[0]


def regrade(trace_path: Path, *, skill: str, platform: str) -> EvalResult:
    trace_path = Path(trace_path)
    adapter = get_adapter(platform)
    run = adapter.parse_stream(trace_path.read_text())

    cfg = load_skill(skill)
    prompt_id = _prompt_id_from_path(trace_path)
    prompt = next((p for p in cfg.prompts if p.id == prompt_id), None)
    if prompt is None:
        raise ValueError(f"no prompt '{prompt_id}' in skill '{skill}'")

    did_trigger = adapter.detect_trigger(run, skill)
    return grade(prompt, run, cfg.checks, platform=platform, skill=skill,
                 did_trigger=did_trigger)
