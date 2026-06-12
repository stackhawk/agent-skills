"""Aggregate baseline cell.json files into shields.io endpoint badge JSONs.

One badge per tool x model combo, pass rate aggregated across all skills.
The combo set is derived from whatever cells exist - never hardcoded - so
adding or removing tools/models in the eval matrix flows through untouched.
"""
from __future__ import annotations

import re

from evals.lib.models import CellReport

# Canonical README ordering; unknown tools sort after these, alphabetically.
# Intentionally the capture-baseline matrix order, NOT reporting._PLATFORM_ORDER
# (which interleaves cursor/agy differently and includes copilot).
TOOL_ORDER = ["claude-code", "codex", "agy", "cursor"]


def cell_ran(cell: CellReport) -> bool:
    """Mirror the digest rollup's plumbing test: a cell ran if any result
    lacks a harness-failure note (see reporting._rollup_cell)."""
    return any(not (r.note or "").strip() for r in cell.results)


def _combo_sort_key(combo: tuple[str, str]) -> tuple[int, str, str]:
    tool, model = combo
    idx = TOOL_ORDER.index(tool) if tool in TOOL_ORDER else len(TOOL_ORDER)
    return (idx, tool, model)


def aggregate(cells: dict[tuple[str, str, str], CellReport]) -> list[dict]:
    """Collapse (platform, skill, model) cells into one row per (tool, model).

    Pass rate counts pass + pass-slow verdicts over the runs that actually ran
    (empty note) within cells that ran at all. A combo whose cells are all
    plumbing-dead is status no-data.
    """
    combos: dict[tuple[str, str], list[CellReport]] = {}
    for (platform, _skill, model), cell in cells.items():
        combos.setdefault((platform, model), []).append(cell)

    rows: list[dict] = []
    for (tool, model) in sorted(combos, key=_combo_sort_key):
        live = [c for c in combos[(tool, model)] if cell_ran(c)]
        if not live:
            rows.append({"tool": tool, "model": model, "passed": 0, "total": 0,
                         "rate": None, "status": "no-data"})
            continue
        results = [r for c in live for r in c.results if not (r.note or "").strip()]
        passed = sum(1 for r in results if r.verdict.value in ("pass", "pass-slow"))
        rows.append({"tool": tool, "model": model, "passed": passed,
                     "total": len(results), "rate": passed / len(results),
                     "status": "ok"})
    return rows


def color_for(rate: float | None) -> str:
    """Shields color from pass rate. Extends the digest's 3-tier convention
    (all-pass / >=80 / below) with a green step at >=90 for README polish."""
    if rate is None:
        return "lightgrey"
    if rate == 1.0:
        return "brightgreen"
    if rate >= 0.9:
        return "green"
    if rate >= 0.8:
        return "yellow"
    return "red"


def display_model(model: str) -> str:
    """Short display form: drop the redundant claude- prefix and any
    trailing date stamp (matches reporting._short_model's -\\d{6,} rule).
    Filenames keep the full model id."""
    out = model.removeprefix("claude-")
    out = re.sub(r"-\d{6,}$", "", out)
    return out or model


def endpoint_json(row: dict) -> dict:
    """One shields.io endpoint-badge JSON (schemaVersion 1) for a combo row.
    Percent is floored so anything short of all-pass never displays 100%."""
    label = f"{row['tool']} · {display_model(row['model'])}"
    if row["status"] == "no-data":
        return {"schemaVersion": 1, "label": label,
                "message": "no data", "color": "lightgrey"}
    pct = int(row["rate"] * 100)
    return {"schemaVersion": 1, "label": label,
            "message": f"{pct}% ({row['passed']}/{row['total']})",
            "color": color_for(row["rate"])}
