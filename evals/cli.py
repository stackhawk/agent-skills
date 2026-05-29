"""Unified eval CLI. Entry points: evals, compare, regrade, validate."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evals.lib.config import load_skill
from evals.lib.grading import grade
from evals.lib.harness import get_adapter
from evals.lib.replay import regrade as _regrade
from evals.lib.reporting import build_summary, render_table, render_compare, console
from evals.lib.compare import compare_skill

PLATFORMS = ["claude-code", "codex", "cursor", "copilot", "agy"]
RESULTS_ROOT = Path(__file__).resolve().parent / "harnesses"


def _common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    p.add_argument("--harness", default="claude-code", choices=PLATFORMS)
    p.add_argument("--id", dest="prompt_id")
    p.add_argument("--model")
    p.add_argument("--max-budget", type=float, default=0.20)
    p.add_argument("--bare", action="store_true")
    p.add_argument("--full-auto", action="store_true")


def main() -> None:
    ap = argparse.ArgumentParser(prog="evals")
    _common_args(ap)
    args = ap.parse_args()

    cfg = load_skill(args.skill)
    adapter = get_adapter(args.harness)
    plugin_dirs = [str(Path.cwd() / "plugins" / args.skill)]
    prompts = [p for p in cfg.prompts if not args.prompt_id or p.id == args.prompt_id]
    if not prompts:
        print(f"no prompt '{args.prompt_id}'", file=sys.stderr); sys.exit(1)

    results = []
    out_dir = RESULTS_ROOT / args.harness / "results" / args.skill
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in prompts:
        run = adapter.launch(p.prompt, args.skill, p.id, plugin_dirs,
                             model=args.model, load_skill=True,
                             max_budget=args.max_budget, bare=args.bare,
                             full_auto=args.full_auto)
        did = adapter.detect_trigger(run, args.skill)
        res = grade(p, run, cfg.checks, platform=args.harness, skill=args.skill,
                    did_trigger=did)
        results.append(res)
        (out_dir / f"{p.id}.result.json").write_text(res.model_dump_json(indent=2))

    render_table(results)
    summary = build_summary(args.skill, args.harness, results)
    summary["timestamp"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    from evals.lib.models import CellReport
    import subprocess as _sp
    commit = _sp.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                     text=True).stdout.strip() or "unknown"
    cell = CellReport(platform=args.harness, skill=args.skill,
                      model=args.model or "default", commit=commit, results=results)
    (out_dir / "cell.json").write_text(cell.model_dump_json(indent=2))

    if summary["false_positives"] or summary["false_negatives"] or \
            summary["total_blocking_failures"] > 0:
        sys.exit(1)


def compare() -> None:
    ap = argparse.ArgumentParser(prog="compare")
    _common_args(ap)
    args = ap.parse_args()
    rows = compare_skill(args.skill, args.harness, model=args.model,
                         max_budget=args.max_budget, bare=args.bare,
                         full_auto=args.full_auto, only_id=args.prompt_id)
    render_compare(rows)


def regrade() -> None:
    ap = argparse.ArgumentParser(prog="regrade")
    ap.add_argument("trace", type=Path)
    ap.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    ap.add_argument("--harness", default="claude-code", choices=PLATFORMS)
    args = ap.parse_args()
    res = _regrade(args.trace, skill=args.skill, platform=args.harness)
    render_table([res])


def validate() -> None:
    ap = argparse.ArgumentParser(prog="validate")
    ap.add_argument("--skill", choices=["hawkscan", "api"])
    args = ap.parse_args()
    skills = [args.skill] if args.skill else ["hawkscan", "api"]
    for skill in skills:
        cfg = load_skill(skill)   # raises on any validation error
        console.print(f"[green]✓[/] {skill}: {len(cfg.prompts)} prompts, "
                      f"{len(cfg.checks)} checks valid")
