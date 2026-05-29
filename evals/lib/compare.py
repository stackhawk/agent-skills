"""Run each should_trigger prompt with and without the skill loaded; report lift."""
from __future__ import annotations
from pathlib import Path

from evals.lib.config import load_skill
from evals.lib.grading import grade
from evals.lib.harness import get_adapter
from evals.lib.models import Verdict


def compare_skill(skill: str, platform: str, *, model: str | None = None,
                  max_budget: float = 0.20, bare: bool = False,
                  full_auto: bool = False, only_id: str | None = None) -> list[dict]:
    cfg = load_skill(skill)
    adapter = get_adapter(platform)
    plugin_dirs = [str(Path.cwd() / "plugins" / skill)]
    prompts = [p for p in cfg.prompts
               if p.should_trigger and (not only_id or p.id == only_id)]

    rows = []
    for p in prompts:
        graded = {}
        for load in (True, False):
            run = adapter.launch(p.prompt, skill, f"{p.id}-{'with' if load else 'without'}",
                                 plugin_dirs, model=model, load_skill=load,
                                 max_budget=max_budget, bare=bare, full_auto=full_auto)
            did = adapter.detect_trigger(run, skill)
            graded[load] = grade(p, run, cfg.checks, platform=platform, skill=skill,
                                 did_trigger=did)
        wv = graded[True].verdict
        wo = graded[False].verdict
        if wo == Verdict.FAIL and wv != Verdict.FAIL:
            effect = "lift"
        elif wo != Verdict.FAIL and wv == Verdict.FAIL:
            effect = "regress"
        else:
            effect = "none"
        rows.append({
            "id": p.id,
            "with_verdict": wv,
            "without_verdict": wo,
            "with_cost": graded[True].cost_usd,
            "without_cost": graded[False].cost_usd,
            "effect": effect,
        })
    return rows
