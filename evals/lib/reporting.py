"""Summaries + rich rendering for eval runs."""
from __future__ import annotations
import os
import re
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


_PLATFORM_ORDER = {p: i for i, p in
                   enumerate(["claude-code", "codex", "cursor", "agy", "copilot"])}
_PIVOT_ICON = {"pass": "✅", "pass-slow": "◆", "fail": "❌"}


def _short_model(model: str) -> str:
    """Compact column label: drop a trailing date stamp and a redundant
    'claude-' prefix. 'claude-haiku-4-5-20251001' -> 'haiku-4-5'; 'o3' -> 'o3'."""
    m = re.sub(r"-\d{6,}$", "", model)
    if m.startswith("claude-"):
        m = m[len("claude-"):]
    return m or model


def _id_sort_key(run_id: str):
    m = re.search(r"(\d+)", run_id)
    return (int(m.group(1)) if m else 0, run_id)


def _fail_reason(r: EvalResult) -> str:
    reason = (r.note or "").strip()
    if not reason:
        if not r.trigger_correct:
            reason = "false-positive" if r.did_trigger else "false-negative"
        elif r.budget_breaches:
            reason = "; ".join(r.budget_breaches)
        else:
            reason = "blocking check failed"
    reason = reason.replace("|", "/").replace("\n", " ").strip()
    return reason[:69] + "…" if len(reason) > 70 else reason


def _pivot_cell(r: EvalResult | None) -> str:
    """One matrix cell: emoji, plus a terse reason on non-pass outcomes."""
    if r is None:
        return "·"   # this harness/model didn't run this test
    v = r.verdict.value
    if v == "pass":
        return _PIVOT_ICON["pass"]
    if v == "pass-slow":
        why = "; ".join(r.budget_breaches) or "slow"
        return f"{_PIVOT_ICON['pass-slow']} — {why}"[:74]
    return f"{_PIVOT_ICON['fail']} — {_fail_reason(r)}"


def render_digest(cells, baselines=None, lift=None) -> str:
    """One aggregated pivot table for the whole matrix.

    Rows are tests (skill/id); columns are platform-model combos; each cell is a
    verdict emoji followed by a short reason on failures. Replaces the previous
    per-cell tables so the Actions run summary holds a single table.
    """
    out = ["<!-- skill-eval-comment -->", "## Skill Eval Results\n"]
    if not cells:
        out.append("_No results._\n")
        return "\n".join(out) + "\n"

    cols = sorted({(c.platform, c.model) for c in cells},
                  key=lambda pm: (_PLATFORM_ORDER.get(pm[0], 99), pm[1]))
    col_label = {pm: f"{pm[0]}-{_short_model(pm[1])}" for pm in cols}

    lookup: dict[tuple, EvalResult] = {}
    row_keys: dict[tuple, bool] = {}
    for c in cells:
        for r in c.results:
            lookup[(c.platform, c.model, c.skill, r.run_id)] = r
            row_keys[(c.skill, r.run_id)] = True
    skill_rank = {"hawkscan": 0, "api": 1}
    rows = sorted(row_keys, key=lambda sr: (skill_rank.get(sr[0], 9), *_id_sort_key(sr[1])))

    out.append("| test | " + " | ".join(col_label[pm] for pm in cols) + " |")
    out.append("|---" * (len(cols) + 1) + "|")
    for skill, rid in rows:
        line = " | ".join(_pivot_cell(lookup.get((pm[0], pm[1], skill, rid)))
                          for pm in cols)
        out.append(f"| {skill}/{rid} | {line} |")
    out.append("")
    out.append("_Legend: ✅ pass · ◆ pass-slow · ❌ fail — reason follows the icon "
               "on non-pass cells; `·` = not run._\n")

    # Optional, compact extras (kept off the main table to avoid the old sprawl).
    if baselines is None:
        out.append("_No baseline available — showing absolute results only._\n")
    else:
        from evals.lib.baseline import diff as _diff, score_delta
        notes = []
        for c in cells:
            base = baselines.get((c.platform, c.skill, c.model))
            if base is None:
                continue
            tag = f"{c.platform}-{_short_model(c.model)}/{c.skill}"
            for k, v in sorted(_diff(c, base).items()):
                if v in ("regressed", "fixed", "changed"):
                    notes.append(f"{badge(v, v)} {tag}:{k}")
            g = [r for r in c.results if r.did_trigger and r.should_trigger]
            bg = [r for r in base.results if r.did_trigger and r.should_trigger]
            avg = sum(r.score for r in g) // len(g) if g else 0
            bavg = sum(r.score for r in bg) // len(bg) if bg else 0
            delta = score_delta(avg, bavg)
            if delta in ("better", "worse"):
                notes.append(f"{badge(delta, delta)} {tag}")
        out.append(("**vs baseline:** " + ", ".join(notes) + "\n") if notes
                   else "_vs baseline: no changes._\n")

    if lift:
        out.append("\n### Skill lift (with vs without)\n")
        for key, rws in lift.items():
            lifted = sum(1 for r in rws if r["effect"] == "lift")
            out.append(f"**{key[0]} · {key[1]} · {key[2]}** — "
                       f"{lifted}/{len(rws)} prompts lifted FAIL→PASS\n")
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
        if r.note:
            why = f"{why} — {r.note}" if why else r.note
        rows.append(f"| {r.run_id} | {_VERDICT_ICON[r.verdict.value]} | {why} |")
    return head + "\n".join(rows) + "\n"
