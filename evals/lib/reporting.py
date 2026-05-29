"""Summaries + rich rendering for eval runs."""
from __future__ import annotations
from collections import Counter

from rich.console import Console
from rich.table import Table

from evals.lib.models import EvalResult, Verdict

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
