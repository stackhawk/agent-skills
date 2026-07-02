#!/usr/bin/env python3
"""Aggregate discovery-eval cells into a single-arm PULSE report.

This is not a benchmark (no OLD-vs-NEW arms). It runs the current skill against
each real repo and scores the discovery output against that repo's answer key, so
we keep a pulse on whether the discovery flow is still healthy over time.

Scoring: each of the six factors is worth correct=2, partial=1, wrong=0 (max 12).
A repo PASSES when its score >= PASS_THRESHOLD (default 9/12) AND the must-hit
factors (technology, api_style, host) are not wrong.
"""
import argparse, json, os, statistics
from pathlib import Path

FACTORS = ["technology", "run_command", "host", "api_style", "spa", "auth"]
MUST_HIT = ["technology", "api_style", "host"]
POINTS = {"correct": 2, "partial": 1, "wrong": 0}
MAX_SCORE = 2 * len(FACTORS)
PASS_THRESHOLD = int(os.environ.get("PASS_THRESHOLD", "9"))


def _load(cell):
    checks = json.loads((cell / "checks.json").read_text()) if (cell / "checks.json").exists() else {}
    grade = json.loads((cell / "grade.json").read_text()) if (cell / "grade.json").exists() else {}
    return {
        **checks,
        "exploratory_score": grade.get("exploratory_score"),
        "jumped_to_conclusion": grade.get("jumped_to_conclusion"),
        "correctness": grade.get("correctness", {}),
    }


def _score(row):
    c = row.get("correctness") or {}
    return sum(POINTS.get(c.get(f), 0) for f in FACTORS)


def _passed(row):
    c = row.get("correctness") or {}
    if any(c.get(f) == "wrong" for f in MUST_HIT):
        return False
    return _score(row) >= PASS_THRESHOLD


def aggregate(run_dir):
    run_dir = Path(run_dir)
    apps = {}
    for cell in sorted((run_dir / "cells").glob("*")):
        if not (cell / "checks.json").exists() and not (cell / "grade.json").exists():
            continue
        apps[cell.name] = _load(cell)
    return apps


def render_markdown(apps):
    L = ["# HawkScan App-Discovery Eval - Pulse", "",
         f"Current skill vs. hand-built answer keys. Pass = score >= {PASS_THRESHOLD}/{MAX_SCORE} "
         "and no must-hit factor (technology/api_style/host) wrong.", "",
         "## Per-repo scorecard", "",
         "| repo | technology | run_command | host | api_style | spa | auth | score | docs-1st? | breadth | explor(0-3) | PASS |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    n_pass = 0
    for app, r in sorted(apps.items()):
        c = r.get("correctness") or {}
        cells = [c.get(f, "-") for f in FACTORS]
        sc = _score(r)
        ok = _passed(r)
        n_pass += 1 if ok else 0
        L.append(f"| {app} | " + " | ".join(cells) + f" | {sc}/{MAX_SCORE} | "
                 f"{r.get('docs_before_conclusion')} | {r.get('exploration_breadth')} | "
                 f"{r.get('exploratory_score')} | {'PASS' if ok else 'FAIL'} |")
    total = len(apps)
    L += ["", "## Pulse", "",
          f"- **{n_pass}/{total} repos pass** the discovery bar.",
          f"- Mean score: {round(statistics.mean(_score(r) for r in apps.values()), 2) if apps else 0}/{MAX_SCORE}.",
          f"- Read docs before concluding: {sum(1 for r in apps.values() if r.get('docs_before_conclusion'))}/{total}.",
          f"- Fell back to the old grep/node checklist: {sum(1 for r in apps.values() if r.get('ran_legacy_command_menu'))}/{total}.",
          f"- Stayed read-only: {sum(1 for r in apps.values() if r.get('stayed_read_only'))}/{total}.",
          "",
          "Limitations: one run per repo; the answer keys are author-verified; the judge is an LLM "
          "(the deterministic process-checks are the objective backbone)."]
    return "\n".join(L), n_pass, len(apps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    apps = aggregate(a.run)
    md, n_pass, total = render_markdown(apps)
    Path(a.run, "report.json").write_text(json.dumps(apps, indent=2))
    Path(a.run, "report.md").write_text(md)
    print(f"wrote {a.run}/report.md  ({n_pass}/{total} repos pass)")


if __name__ == "__main__":
    main()
