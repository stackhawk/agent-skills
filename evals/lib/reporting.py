"""Summaries + rich rendering for eval runs."""
from __future__ import annotations
import os
from collections import Counter

from rich.console import Console
from rich.table import Table

from evals.lib.models import CellReport, EvalResult, Verdict

console = Console()
DOT = {Verdict.PASS: "[green]● PASS[/]", Verdict.PASS_SLOW: "[yellow]◐ PASS-SLOW[/]",
       Verdict.FAIL: "[red]○ FAIL[/]"}


def build_summary(skill: str, platform: str, results: list[EvalResult]) -> dict:
    correct = sum(1 for r in results if r.trigger_correct)
    fp = [r.run_id for r in results if not r.should_trigger and r.did_trigger]
    fn = [r.run_id for r in results if r.should_trigger and not r.did_trigger]
    counts = Counter(r.verdict.value for r in results)
    graded = [r for r in results if r.did_trigger and r.should_trigger]
    avg = sum(r.score for r in graded) // len(graded) if graded else None
    return {
        "skill": skill, "platform": platform,
        "trigger_accuracy": {"correct": correct, "total": len(results)},
        "false_positives": fp, "false_negatives": fn,
        "verdict_counts": dict(counts), "process_avg_score": avg,
        "total_blocking_failures": sum(
            1 for r in results for c in r.process_checks
            if not c.passed and c.severity == "blocking"),
    }


def render_table(results: list[EvalResult]) -> None:
    t = Table(show_edge=False, box=None, padding=(0, 2))
    for col in ("ID", "Trigger", "Verdict", "Score", "Budget", "Cost"):
        t.add_column(col)
    for r in results:
        trig = "[green]✓[/]" if r.trigger_correct else "[red]✗[/]"
        budget = ", ".join(r.budget_breaches) or "—"
        t.add_row(r.run_id, trig, DOT[r.verdict], str(r.score), budget,
                  f"${r.cost_usd:.3f}")
    console.print(t)


def render_compare(rows: list[dict]) -> None:
    """rows: {id, with_verdict, without_verdict, with_cost, without_cost}."""
    t = Table(show_edge=False, box=None, padding=(0, 2))
    for col in ("ID", "Without skill", "With skill", "Δ"):
        t.add_column(col)
    for row in rows:
        w, wo = row["with_verdict"], row["without_verdict"]
        delta = "[green]↑ lift[/]" if (wo == Verdict.FAIL and w != Verdict.FAIL) else (
                "[red]↓ regress[/]" if (wo != Verdict.FAIL and w == Verdict.FAIL) else "=")
        t.add_row(row["id"], DOT[wo], DOT[w], delta)
    console.print(t)


_BADGE_COLOR = {
    "pass": "brightgreen", "pass-slow": "yellow", "fail": "red",
    "regressed": "red", "fixed": "brightgreen", "changed": "blue",
    "same": "lightgrey", "better": "brightgreen", "worse": "red",
    "no-change": "lightgrey",
}


def badge(kind: str, label: str) -> str:
    color = _BADGE_COLOR.get(kind, "lightgrey")
    safe = label.replace("-", "--").replace(" ", "_")
    return f"![{label}](https://img.shields.io/badge/{safe}-{color})"


_VERDICT_ICON = {"pass": "✅ PASS", "pass-slow": "◆ PASS-SLOW", "fail": "❌ FAIL"}


def _row_rank(r: EvalResult) -> int:
    # failures first (incl. trigger-incorrect), then slow, then pass
    if r.verdict.value == "fail" or not r.trigger_correct:
        return 0
    if r.verdict.value == "pass-slow":
        return 1
    return 2


def write_github_summary(md: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(md)


def render_digest(cells, baselines=None, lift=None) -> str:
    from evals.lib.baseline import diff as _diff, score_delta
    out = ["<!-- skill-eval-comment -->", "## Skill Eval Results\n"]
    out.append("| platform | skill | model | trigger | ✅/◆/❌ | score | vs base |")
    out.append("|---|---|---|---|---|---|---|")
    for cell in cells:
        c = Counter(r.verdict.value for r in cell.results)
        n = len(cell.results); trig = sum(1 for r in cell.results if r.trigger_correct)
        graded = [r for r in cell.results if r.did_trigger and r.should_trigger]
        avg = sum(r.score for r in graded) // len(graded) if graded else 0
        ticon = "✅" if trig == n else "❌"
        vs = "—"
        if baselines is not None:
            b = baselines.get((cell.platform, cell.skill, cell.model))
            if b is not None:
                bg = [r for r in b.results if r.did_trigger and r.should_trigger]
                bavg = sum(r.score for r in bg) // len(bg) if bg else 0
                delta = score_delta(avg, bavg)
                vs = f"{badge(delta, delta)}"
        out.append(f"| {cell.platform} | {cell.skill} | {cell.model} | {ticon} {trig}/{n} | "
                   f"{c.get('pass',0)}/{c.get('pass-slow',0)}/{c.get('fail',0)} | {avg} | {vs} |")
    out.append("")
    if baselines is None:
        out.append("_No baseline available — showing absolute results only._\n")
    for cell in cells:
        out.append(render_job_summary(cell))
        if baselines is not None:
            base = baselines.get((cell.platform, cell.skill, cell.model))
            if base is None:
                out.append("_no baseline for this cell._\n")
            else:
                d = _diff(cell, base)
                changed = {k: v for k, v in d.items()
                           if v in ("regressed", "fixed", "changed")}
                if changed:
                    out.append("**vs baseline:** " + ", ".join(
                        f"{badge(v, v)} {k}" for k, v in sorted(changed.items())) + "\n")
                else:
                    out.append("_vs baseline: no changes._\n")
    if lift:
        out.append("\n### Skill lift (with vs without)\n")
        for key, rows in lift.items():
            lifted = sum(1 for r in rows if r["effect"] == "lift")
            out.append(f"**{key[0]} · {key[1]} · {key[2]}** — "
                       f"{lifted}/{len(rows)} prompts lifted FAIL→PASS\n")
            out.append("| test | without | with | |")
            out.append("|---|---|---|---|")
            for r in rows:
                eff = {"lift": badge('fixed', '↑ lift'),
                       "regress": badge('regressed', '↓ regress'),
                       "none": ""}[r["effect"]]
                out.append(f"| {r['id']} | {r['without_verdict']} | "
                           f"{r['with_verdict']} | {eff} |")
            out.append("")
    return "\n".join(out) + "\n"


def render_job_summary(cell: CellReport) -> str:
    c = Counter(r.verdict.value for r in cell.results)
    trig_ok = sum(1 for r in cell.results if r.trigger_correct)
    n = len(cell.results)
    head = (f"### {cell.platform} · {cell.skill} · {cell.model}  "
            f"— ✅ {c.get('pass',0)} / ◆ {c.get('pass-slow',0)} / "
            f"❌ {c.get('fail',0)}  ·  {c.get('fail',0)} failed  ·  "
            f"trigger {trig_ok}/{n}\n\n")
    rows = ["| test | result | why |", "|---|---|---|"]
    for r in sorted(cell.results, key=lambda r: (_row_rank(r), r.run_id)):
        why = "; ".join(r.budget_breaches) if r.budget_breaches else (
            "" if r.trigger_correct else
            ("false-positive" if r.did_trigger else "false-negative"))
        rows.append(f"| {r.run_id} | {_VERDICT_ICON[r.verdict.value]} | {why} |")
    return head + "\n".join(rows) + "\n"
