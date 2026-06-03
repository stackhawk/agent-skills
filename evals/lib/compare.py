"""Run each should_trigger prompt with and without the skill loaded; report lift."""
from __future__ import annotations
from pathlib import Path

from evals.lib.config import load_skill
from evals.lib.grading import grade
from evals.lib.harness import get_adapter
from evals.lib.models import EvalResult, Verdict


def compare_skill(skill: str, platform: str, *, model: str | None = None,
                  max_budget: float = 0.20, bare: bool = False,
                  full_auto: bool = False, only_id: str | None = None) -> list[dict]:
    cfg = load_skill(skill)
    adapter = get_adapter(platform)
    plugin_dirs = [str(Path.cwd() / "plugins" / skill)]
    prompts = [p for p in cfg.prompts
               if p.should_trigger and (not only_id or p.id == only_id)]
    # If toggling the skill is a no-op for this platform (e.g. agy installs skills
    # globally), with/without runs are identical and lift can't be measured.
    noop = getattr(adapter, "load_skill_is_noop", False)

    rows = []
    for p in prompts:
        graded = {}
        for load in (True, False):
            run_id = f"{p.id}-{'with' if load else 'without'}"
            # Mirror the evals CLI: never let one prompt's harness failure abort the
            # whole compare loop (which would leave a half-written lift.json).
            try:
                run = adapter.launch(p.prompt, skill, run_id, plugin_dirs,
                                     model=model, load_skill=load,
                                     max_budget=max_budget, bare=bare,
                                     full_auto=full_auto)
                did = adapter.detect_trigger(run, skill)
                graded[load] = grade(p, run, cfg.checks, platform=platform,
                                     skill=skill, did_trigger=did)
            except Exception as e:  # noqa: BLE001 — record the failure, keep going
                graded[load] = EvalResult(
                    platform=platform, skill=skill, run_id=run_id,
                    should_trigger=p.should_trigger, did_trigger=False,
                    trigger_correct=(not p.should_trigger),
                    verdict=Verdict.FAIL if p.should_trigger else Verdict.PASS,
                    score=0 if p.should_trigger else 100,
                    note=f"harness exception: {type(e).__name__}: {e}")
        wv = graded[True].verdict
        wo = graded[False].verdict
        if wo == Verdict.FAIL and wv != Verdict.FAIL:
            effect = "lift"
        elif wo != Verdict.FAIL and wv == Verdict.FAIL:
            effect = "regress"
        else:
            effect = "none"
        row = {
            "id": p.id,
            "with_verdict": wv,
            "without_verdict": wo,
            "with_cost": graded[True].cost_usd,
            "without_cost": graded[False].cost_usd,
            "effect": effect,
        }
        if noop:
            row["note"] = "skill installed globally — with/without identical; lift not measurable"
        rows.append(row)
    return rows
