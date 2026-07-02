#!/usr/bin/env python3
"""Aggregate benchmark cells into an OLD-vs-NEW comparison report.

Signal-agnostic: it renders whatever process-check signals the benchmark's
`grade.py`/`checks.py` emitted (the union across cells), plus judge and
task-completion metrics when present. Nothing here is hypothesis-specific."""
import argparse, json, statistics
from pathlib import Path


def _load(cell):
    checks = json.loads((cell / "checks.json").read_text()) if (cell / "checks.json").exists() else {}
    grade = json.loads((cell / "grade.json").read_text()) if (cell / "grade.json").exists() else {}
    return {"checks": checks, "grade": grade}


def _correct_count(grade):
    return sum(1 for x in (grade.get("correctness") or {}).values() if x == "correct")


def aggregate(run_dir):
    run_dir = Path(run_dir)
    apps = {}
    for cell in sorted((run_dir / "cells").glob("*__*")):
        arm, app = cell.name.split("__", 1)
        apps.setdefault(app, {})[arm] = _load(cell)

    # union of check-signal keys across all cells — driven by the benchmark, not hard-coded
    signal_keys = []
    for arms in apps.values():
        for r in arms.values():
            for k in r["checks"]:
                if k not in signal_keys:
                    signal_keys.append(k)

    means = {}
    for arm in ("old", "new"):
        rows = [v[arm] for v in apps.values() if arm in v]
        if not rows:
            continue
        m = {}
        for k in signal_keys:
            vals = [r["checks"].get(k) for r in rows if r["checks"].get(k) is not None]
            if not vals:
                continue
            if all(isinstance(v, bool) for v in vals):
                m[f"{k}_rate"] = round(sum(1 for v in vals if v) / len(vals), 3)
            elif all(isinstance(v, (int, float)) for v in vals):
                m[k] = round(statistics.mean(vals), 2)
        grades = [r["grade"] for r in rows if r["grade"]]
        if grades:
            es = [g["exploratory_score"] for g in grades if isinstance(g.get("exploratory_score"), (int, float))]
            if es:
                m["exploratory_score"] = round(statistics.mean(es), 2)
            pg = [g["pigeonholed"] for g in grades if isinstance(g.get("pigeonholed"), bool)]
            if pg:
                m["pigeonholed_rate"] = round(sum(1 for v in pg if v) / len(pg), 3)
            cc = [_correct_count(g) for g in grades if g.get("correctness")]
            if cc:
                m["answers_correct"] = round(statistics.mean(cc), 2)
            cr = [g["close_rate"] for g in grades if isinstance(g.get("close_rate"), (int, float))]
            if cr:
                m["close_rate"] = round(statistics.mean(cr), 3)
                for k in ("coverage_not_reduced", "app_not_broken"):
                    vv = [g[k] for g in grades if isinstance(g.get(k), bool)]
                    if vv:
                        m[f"{k}_rate"] = round(sum(1 for v in vv if v) / len(vv), 3)
        means[arm] = m
    return {"apps": apps, "signal_keys": signal_keys, "means": means}


def render_markdown(agg):
    signal_keys = agg["signal_keys"]
    has_grade = any(r["grade"] for arms in agg["apps"].values() for r in arms.values())

    L = ["# Benchmark A/B — OLD vs NEW", "", "## Per-app signals", ""]
    header = ["app", "arm"] + signal_keys + (["explor", "pigeonholed", "#correct"] if has_grade else [])
    L.append("| " + " | ".join(header) + " |")
    L.append("|" + "|".join(["---"] * len(header)) + "|")
    for app, arms in sorted(agg["apps"].items()):
        for arm in ("old", "new"):
            r = arms.get(arm)
            if not r:
                continue
            row = [app, arm.upper()] + [str(r["checks"].get(k)) for k in signal_keys]
            if has_grade:
                g = r["grade"]
                row += [str(g.get("exploratory_score")), str(g.get("pigeonholed")), str(_correct_count(g))]
            L.append("| " + " | ".join(row) + " |")

    L += ["", "## Means across apps", "", "| metric | OLD | NEW |", "|---|---|---|"]
    metric_keys = []
    for arm in ("old", "new"):
        for k in agg["means"].get(arm, {}):
            if k not in metric_keys:
                metric_keys.append(k)
    for k in metric_keys:
        L.append(f"| {k} | {agg['means'].get('old', {}).get(k)} | {agg['means'].get('new', {}).get(k)} |")

    L += ["", "## Verdict",
          "- Compare NEW vs OLD on the signal(s) your hypothesis targeted, and confirm nothing you cared about regressed.",
          "- Limitations: small n, 1 run/cell — directional, not statistically significant; ground truth is author-judged; the judge is an LLM, so the deterministic process-checks are the objective backbone."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    agg = aggregate(a.run)
    Path(a.run, "report.json").write_text(json.dumps(agg, indent=2))
    Path(a.run, "report.md").write_text(render_markdown(agg))
    print(f"wrote {a.run}/report.md")


if __name__ == "__main__":
    main()
