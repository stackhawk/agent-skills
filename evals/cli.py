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
    p.add_argument("--skill", required=True, choices=["hawkscan", "api", "stackhawk-data-seed", "hawkscan-ci", "optimize"])
    p.add_argument("--harness", default="claude-code", choices=PLATFORMS)
    p.add_argument("--id", dest="prompt_id")
    p.add_argument("--model")
    p.add_argument("--max-budget", type=float, default=0.20)
    p.add_argument("--bare", action="store_true")
    p.add_argument("--full-auto", action="store_true")
    p.add_argument("--rubric", action="store_true",
                   help="also run the qualitative model-graded rubric (needs ANTHROPIC_API_KEY)")


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

    from evals.lib.models import EvalResult, Verdict
    results = []
    out_dir = RESULTS_ROOT / args.harness / "results" / args.skill
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in prompts:
        try:
            run = adapter.launch(p.prompt, args.skill, p.id, plugin_dirs,
                                 model=args.model, load_skill=True,
                                 max_budget=args.max_budget, bare=args.bare,
                                 full_auto=args.full_auto, target_repo=p.target_repo)
            if p.answer_key:
                # Discovery cell: graded on the discovery axis (judge + its own
                # process-checks), not the scan-trigger/global-checks path.
                from pathlib import Path as _P
                from evals.lib.rubric import judge_answer_key, parse_discovery_block
                from evals.lib.grading import grade_discovery
                key_path = _P(__file__).resolve().parent / args.skill / p.answer_key
                judge_checks = []
                # Skip the (costly) claude grader call on a broken cell -- if the
                # run errored or produced no DISCOVERY: block, there's nothing for
                # the judge to grade. grade_discovery's own `expected` checks still
                # run and will fail the cell as before.
                if not run.error and parse_discovery_block(run.output_text):
                    try:
                        judge_checks = judge_answer_key(run, str(key_path))
                    except Exception as e:  # judge is best-effort; don't abort the cell
                        run.error = run.error or f"judge failed: {type(e).__name__}: {e}"
                res = grade_discovery(p, run, cfg.checks, judge_checks,
                                      platform=args.harness, skill=args.skill)
            elif p.own_checks_only:
                # Reasoning-only cell (e.g. post-scan gate): grade on its own
                # applies_to checks + expected, not the global scan-flow checks
                # (preflight/step1/scan) that a paper exercise never performs.
                from evals.lib.grading import grade_discovery
                res = grade_discovery(p, run, cfg.checks, [],
                                      platform=args.harness, skill=args.skill)
            else:
                did = adapter.detect_trigger(run, args.skill)
                res = grade(p, run, cfg.checks, platform=args.harness, skill=args.skill,
                            did_trigger=did, extended=args.full_auto)
                # Qualitative rubric: EXTENDED-ONLY. It grades output-presentation
                # quality (formatted posture tables, platform links, severity
                # breakdowns) that only exists when the agent executes against a
                # real target. Running it on observe-mode narration scores ~0
                # everywhere (noise), so it runs only under --full-auto, and only
                # when the skill triggered correctly.
                if args.rubric and args.full_auto and res.trigger_correct and did:
                    from evals.lib.rubric import grade_rubric
                    res.rubric = grade_rubric(run, args.skill, p.id)
            # persist a trace for visibility (uploaded with the artifact)
            trace = (f"# {p.id} (returncode={run.returncode})\n"
                     f"## error\n{run.error or ''}\n"
                     f"## stderr_tail\n{run.stderr_tail}\n"
                     f"## guard_denials\n" + "\n".join(run.guard_denials) + "\n"
                     f"## output_text\n{run.output_text}\n"
                     f"## bash_commands\n" + "\n".join(run.bash_commands) + "\n")
            (out_dir / f"{p.id}.trace.txt").write_text(trace)
        except Exception as e:  # noqa: BLE001 — never let one prompt abort the cell
            res = EvalResult(platform=args.harness, skill=args.skill, run_id=p.id,
                             should_trigger=p.should_trigger, did_trigger=False,
                             trigger_correct=(not p.should_trigger),
                             verdict=Verdict.FAIL if p.should_trigger else Verdict.PASS,
                             score=0 if p.should_trigger else 100,
                             note=f"harness exception: {type(e).__name__}: {e}")
            (out_dir / f"{p.id}.trace.txt").write_text(
                f"# {p.id}\n## harness exception\n{type(e).__name__}: {e}\n")
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
    # Note: individual cells no longer write to GITHUB_STEP_SUMMARY — the `report`
    # job aggregates every cell.json into one pivot table (render_digest), so the
    # run summary holds a single table instead of one per matrix cell.

    # CI semantics: the job is GREEN when the eval RAN, not when every skill
    # passed. Per-cell pass/fail (FP/FN/blocking) is data in the report table —
    # the ship signal you read, not the build's success criterion. The job goes
    # RED only on a plumbing failure: the eval couldn't actually run the agent
    # for ANY prompt (missing/unauthenticated CLI, timeouts everywhere, harness
    # exceptions). A clean run has note == "" ; any non-empty note is a prompt
    # that didn't execute.
    ran = [r for r in results if not (r.note or "").strip()]
    if results and not ran:
        notes = sorted({(r.note or "").strip()[:80] for r in results if (r.note or "").strip()})
        print(f"PLUMBING FAILURE: eval ran 0/{len(results)} prompts cleanly for "
              f"{args.harness}/{args.skill}. Causes: {notes}", file=sys.stderr)
        sys.exit(1)


def compare() -> None:
    ap = argparse.ArgumentParser(prog="compare")
    _common_args(ap)
    args = ap.parse_args()
    rows = compare_skill(args.skill, args.harness, model=args.model,
                         max_budget=args.max_budget, bare=args.bare,
                         full_auto=args.full_auto, only_id=args.prompt_id)
    out_dir = Path(__file__).resolve().parent / "harnesses" / args.harness / "results" / args.skill
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "lift.json").write_text(json.dumps(
        [{**r, "with_verdict": r["with_verdict"].value,
          "without_verdict": r["without_verdict"].value} for r in rows], indent=2))
    render_compare(rows)


def regrade() -> None:
    ap = argparse.ArgumentParser(prog="regrade")
    ap.add_argument("trace", type=Path)
    ap.add_argument("--skill", required=True, choices=["hawkscan", "api", "stackhawk-data-seed", "hawkscan-ci", "optimize"])
    ap.add_argument("--harness", default="claude-code", choices=PLATFORMS)
    args = ap.parse_args()
    res = _regrade(args.trace, skill=args.skill, platform=args.harness)
    render_table([res])


def report() -> None:
    import argparse
    from pathlib import Path
    from evals.lib.models import CellReport
    from evals.lib.reporting import render_digest
    ap = argparse.ArgumentParser(prog="report")
    ap.add_argument("--pr", action="store_true")
    ap.add_argument("--results-dir", type=Path, default=Path("results"))
    ap.add_argument("--baseline-dir", type=Path, default=None)
    ap.add_argument("--lift-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("digest.md"))
    ap.add_argument("--title", default="Skill Eval Results")
    args = ap.parse_args()
    cells = []
    for cj in sorted(args.results_dir.rglob("cell.json")):
        try:
            cells.append(CellReport.model_validate_json(cj.read_text()))
        except Exception:
            continue
    from evals.lib.baseline import load_baseline_dir
    baselines = load_baseline_dir(args.baseline_dir) or None
    lift = None
    if args.lift_dir and args.lift_dir.exists():
        lift = {}
        for lj in args.lift_dir.rglob("lift.json"):
            sib = lj.parent / "cell.json"
            if not sib.exists():
                continue
            cell = CellReport.model_validate_json(sib.read_text())
            lift[(cell.platform, cell.skill, cell.model)] = json.loads(lj.read_text())
        lift = lift or None
    md = render_digest(cells, baselines=baselines, lift=lift, title=args.title)
    args.out.write_text(md)
    print(f"wrote {args.out} ({len(cells)} cells)")


def validate() -> None:
    ap = argparse.ArgumentParser(prog="validate")
    ap.add_argument("--skill", choices=["hawkscan", "api", "stackhawk-data-seed", "hawkscan-ci", "optimize"])
    args = ap.parse_args()
    skills = [args.skill] if args.skill else ["hawkscan", "api", "stackhawk-data-seed", "hawkscan-ci", "optimize"]
    for skill in skills:
        cfg = load_skill(skill)   # raises on any validation error
        console.print(f"[green]✓[/] {skill}: {len(cfg.prompts)} prompts, "
                      f"{len(cfg.checks)} checks valid")


def badges() -> None:
    """Generate shields endpoint badge JSONs from baseline cell.json files,
    and/or rewrite the README badge block from a matrix.json."""
    import argparse
    import json as _json
    from pathlib import Path
    from evals.lib.badges import render_block, replace_block, write_outputs

    ap = argparse.ArgumentParser(prog="badges")
    ap.add_argument("--baseline-dir", type=Path,
                    help="dir tree containing baseline cell.json files")
    ap.add_argument("--out", type=Path,
                    help="output dir for endpoint JSONs + matrix.json")
    ap.add_argument("--tag", default="", help="release tag being baselined")
    ap.add_argument("--run-url", default="", help="capture-baseline run URL")
    ap.add_argument("--render-readme", type=Path,
                    help="README path: rewrite its badge block from --matrix")
    ap.add_argument("--matrix", type=Path,
                    help="path to matrix.json (defaults to <out>/matrix.json when --out is also passed)")
    args = ap.parse_args()

    if not args.baseline_dir and not args.render_readme:
        ap.error("nothing to do: pass --baseline-dir and/or --render-readme")

    if args.baseline_dir:
        if not args.out:
            ap.error("--out is required with --baseline-dir")
        from evals.lib.baseline import load_baseline_dir
        cells = load_baseline_dir(args.baseline_dir)
        if not cells:
            raise SystemExit(f"no parseable cell.json files found under {args.baseline_dir}")
        matrix = write_outputs(cells, args.out, tag=args.tag, run_url=args.run_url)
        print(f"wrote {len(matrix['combos'])} badge(s) + matrix.json to {args.out}")

    if args.render_readme:
        matrix_path = args.matrix or (args.out / "matrix.json" if args.out else None)
        if not matrix_path or not matrix_path.exists():
            ap.error("--render-readme requires --matrix or --out (so matrix.json can be resolved)")
        matrix = _json.loads(matrix_path.read_text())
        if "combos" not in matrix:
            raise SystemExit(f"matrix.json at {matrix_path} is missing 'combos' key")
        readme = args.render_readme.read_text()
        args.render_readme.write_text(replace_block(readme, render_block(matrix)))
        print(f"updated badge block in {args.render_readme}")
