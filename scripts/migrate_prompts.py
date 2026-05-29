#!/usr/bin/env python3
"""One-time, idempotent migration of evals/<skill>/prompts.csv -> prompts.yaml.
Preserves id, should_trigger (bool), invocation_type, prompt, notes. Adds no
budgets or expected[] — those are authored by hand afterward."""
from __future__ import annotations
import csv
import sys
from pathlib import Path

import yaml

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"


def migrate(skill: str) -> None:
    csv_path = EVALS_DIR / skill / "prompts.csv"
    yaml_path = EVALS_DIR / skill / "prompts.yaml"
    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["id"],
                "should_trigger": r["should_trigger"].strip().lower() == "true",
                "invocation_type": r["invocation_type"],
                "prompt": r["prompt"],
                "notes": r.get("notes", ""),
            })
    yaml_path.write_text(yaml.safe_dump(rows, sort_keys=False, width=100,
                                        allow_unicode=True))
    print(f"wrote {yaml_path} ({len(rows)} prompts)")


if __name__ == "__main__":
    for skill in (sys.argv[1:] or ["hawkscan", "api"]):
        migrate(skill)
