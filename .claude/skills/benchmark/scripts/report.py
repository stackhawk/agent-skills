#!/usr/bin/env python3
"""Aggregate discovery-eval cells into an OLD-vs-NEW comparison report."""
import argparse, json, statistics
from pathlib import Path

BOOL_SIGNALS = ["read_agent_docs","docs_before_conclusion","explored_manifests","emitted_five_answers","stayed_read_only","ran_legacy_command_menu"]

def _load(cell):
    checks = json.loads((cell/"checks.json").read_text()) if (cell/"checks.json").exists() else {}
    grade = json.loads((cell/"grade.json").read_text()) if (cell/"grade.json").exists() else {}
    return {**checks,
            "exploratory_score": grade.get("exploratory_score"),
            "pigeonholed": grade.get("pigeonholed"),
            "correctness": grade.get("correctness", {}),
            "close_rate": grade.get("close_rate"),
            "coverage_not_reduced": grade.get("coverage_not_reduced"),
            "app_not_broken": grade.get("app_not_broken")}

def aggregate(run_dir):
    run_dir = Path(run_dir); apps = {}
    for cell in sorted((run_dir/"cells").glob("*__*")):
        arm, app = cell.name.split("__", 1)
        apps.setdefault(app, {})[arm] = _load(cell)
    means = {}
    for arm in ("old","new"):
        rows = [v[arm] for v in apps.values() if arm in v]
        if not rows: continue
        def rate(k): return round(sum(1 for r in rows if r.get(k)) / len(rows), 3)
        def correct_count(r): return sum(1 for x in (r.get("correctness") or {}).values() if x == "correct")
        means[arm] = {
            "read_agent_docs_rate": rate("read_agent_docs"),
            "docs_before_conclusion_rate": rate("docs_before_conclusion"),
            "explored_manifests_rate": rate("explored_manifests"),
            "legacy_menu_rate": rate("ran_legacy_command_menu"),
            "pigeonholed_rate": rate("pigeonholed"),
            "exploration_breadth": round(statistics.mean(r.get("exploration_breadth") or 0 for r in rows), 2),
            "exploratory_score": round(statistics.mean(r.get("exploratory_score") or 0 for r in rows), 2),
            "answers_correct": round(statistics.mean(correct_count(r) for r in rows), 2),
        }
        close_rates = [r.get("close_rate") for r in rows if r.get("close_rate") is not None]
        if close_rates:
            means[arm]["close_rate"] = round(statistics.mean(close_rates), 3)
            means[arm]["coverage_not_reduced_rate"] = rate("coverage_not_reduced")
            means[arm]["app_not_broken_rate"] = rate("app_not_broken")
    return {"apps": apps, "means": means}

def render_markdown(agg):
    L = ["# HawkScan App-Discovery A/B — OLD (v2.0.0) vs NEW (v2.1.0)", "",
         "## Per-app signals", "",
         "| app | arm | docs? | docs-1st? | manifests? | breadth | legacy-menu? | explor(0-3) | pigeonholed? | #correct |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for app, arms in sorted(agg["apps"].items()):
        for arm in ("old","new"):
            r = arms.get(arm)
            if not r: continue
            nc = sum(1 for x in (r.get("correctness") or {}).values() if x == "correct")
            L.append(f"| {app} | {arm.upper()} | {r.get('read_agent_docs')} | {r.get('docs_before_conclusion')} | "
                     f"{r.get('explored_manifests')} | {r.get('exploration_breadth')} | {r.get('ran_legacy_command_menu')} | "
                     f"{r.get('exploratory_score')} | {r.get('pigeonholed')} | {nc} |")
    L += ["", "## Means across apps", "", "| metric | OLD | NEW |", "|---|---|---|"]
    m = agg["means"]
    for k in ["read_agent_docs_rate","docs_before_conclusion_rate","explored_manifests_rate","exploration_breadth","legacy_menu_rate","exploratory_score","pigeonholed_rate","answers_correct"]:
        L.append(f"| {k} | {m.get('old',{}).get(k)} | {m.get('new',{}).get(k)} |")
    all_rows = [r for arms in agg["apps"].values() for r in arms.values()]
    if any(r.get("close_rate") is not None for r in all_rows):
        L += ["", "## Task-completion metrics", "", "| metric | OLD | NEW |", "|---|---|---|"]
        for k in ["close_rate","coverage_not_reduced_rate","app_not_broken_rate"]:
            L.append(f"| {k} | {m.get('old',{}).get(k)} | {m.get('new',{}).get(k)} |")
    L += ["", "## Verdict",
          "- **Claim supported** if NEW shows higher docs/exploration/exploratory_score, lower pigeonholed_rate, and answers_correct ≥ OLD.",
          "- Limitations: n=3 apps, 1 run/cell — directional, not statistically significant; ground truth is author-judged; judge is an LLM (stage-1 checks are the objective backbone)."]
    return "\n".join(L)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", required=True); a = ap.parse_args()
    agg = aggregate(a.run)
    Path(a.run, "report.json").write_text(json.dumps(agg, indent=2))
    Path(a.run, "report.md").write_text(render_markdown(agg))
    print(f"wrote {a.run}/report.md")

if __name__ == "__main__":
    main()
