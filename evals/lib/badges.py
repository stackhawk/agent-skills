"""Aggregate baseline cell.json files into shields.io endpoint badge JSONs.

One badge per skill x tool x model. The README groups them into one section
per skill; the (skill, tool, model) set is derived from whatever cells exist -
never hardcoded - so adding or removing skills/tools/models in the eval matrix
flows through untouched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from evals.lib.models import CellReport

# Canonical README ordering; unknown values sort after these, alphabetically.
# TOOL_ORDER is intentionally the capture-baseline matrix order, NOT
# reporting._PLATFORM_ORDER (which interleaves cursor/agy differently and
# includes copilot). SKILL_ORDER mirrors reporting._ROLLUP_SKILLS - the section
# order shown in the digest rollup.
TOOL_ORDER = ["claude-code", "codex", "agy", "cursor"]
SKILL_ORDER = ["hawkscan", "api", "stackhawk-data-seed", "hawkscan-ci"]


def cell_ran(cell: CellReport) -> bool:
    """Mirror the digest rollup's plumbing test: a cell ran if any result
    lacks a harness-failure note (see reporting._rollup_cell)."""
    return any(not (r.note or "").strip() for r in cell.results)


def _row_sort_key(row: dict) -> tuple[int, str, int, str, str]:
    skill, tool, model = row["skill"], row["tool"], row["model"]
    s_idx = SKILL_ORDER.index(skill) if skill in SKILL_ORDER else len(SKILL_ORDER)
    t_idx = TOOL_ORDER.index(tool) if tool in TOOL_ORDER else len(TOOL_ORDER)
    return (s_idx, skill, t_idx, tool, model)


def aggregate(cells: dict[tuple[str, str, str], CellReport]) -> list[dict]:
    """One row per (skill, tool, model) cell - no cross-skill aggregation.

    Each (platform/tool, skill, model) maps to exactly one cell, so this is a
    per-cell map. Pass rate counts pass + pass-slow verdicts over the runs that
    actually ran (empty note); a cell that didn't run at all is status no-data.
    Rows are sorted by skill (section order), then tool, then model.
    """
    rows: list[dict] = []
    for (tool, skill, model), cell in cells.items():  # cells keyed (platform, skill, model); platform == tool
        if not cell_ran(cell):
            rows.append({"skill": skill, "tool": tool, "model": model,
                         "passed": 0, "total": 0, "rate": None, "status": "no-data"})
            continue
        results = [r for r in cell.results if not (r.note or "").strip()]
        passed = sum(1 for r in results if r.verdict.value in ("pass", "pass-slow"))
        rows.append({"skill": skill, "tool": tool, "model": model,
                     "passed": passed, "total": len(results),
                     "rate": passed / len(results), "status": "ok"})
    return sorted(rows, key=_row_sort_key)


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
    The badge label is tool + model; the skill is carried by the README
    section header, not the badge. Percent is floored so anything short of
    all-pass never displays 100%."""
    label = f"{row['tool']} · {display_model(row['model'])}"
    if row["status"] == "no-data":
        return {"schemaVersion": 1, "label": label,
                "message": "no data", "color": "lightgrey"}
    pct = int(row["rate"] * 100)
    return {"schemaVersion": 1, "label": label,
            "message": f"{pct}% ({row['passed']}/{row['total']})",
            "color": color_for(row["rate"])}


def _safe_segment(value: str) -> str:
    """Reject path-escaping skill/tool/model values from artifact-supplied
    cells (a `..` or `a/b` segment would write outside the output tree)."""
    if not value or Path(value).name != value:
        raise SystemExit(f"unsafe path segment in badge output: {value!r}")
    return value


def write_outputs(cells: dict[tuple[str, str, str], CellReport], out: Path,
                  tag: str, run_url: str) -> dict:
    """Write <skill>/<tool>/<model>.json endpoint badges plus matrix.json to `out`.

    Refuses to write anything for an empty cell set - the publish workflow
    must keep the badges branch on its last good state rather than blank it.
    Does not clean ``out/``; stale files from removed combos are handled by
    the publish workflow, which fully replaces the badges branch tree.
    """
    if not cells:
        raise SystemExit("no parseable cell.json baselines found - refusing to publish")
    rows = aggregate(cells)
    out.mkdir(parents=True, exist_ok=True)
    for row in rows:
        combo_dir = out / _safe_segment(row["skill"]) / _safe_segment(row["tool"])
        combo_dir.mkdir(parents=True, exist_ok=True)
        (combo_dir / f"{_safe_segment(row['model'])}.json").write_text(
            json.dumps(endpoint_json(row), indent=2) + "\n")
    matrix = {"schema": 2, "tag": tag, "run_url": run_url, "combos": rows}
    (out / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n")
    return matrix


BLOCK_START = "<!-- eval-badges:start -->"
BLOCK_END = "<!-- eval-badges:end -->"
_REPO = "stackhawk/agent-skills"  # hardcoded: the badges branch lives only in this repo

EVAL_HEADING = "## Eval Results"
EVAL_INTRO = ("Skill eval pass rates at the latest release, broken down by skill. "
              "Each badge is one agent (tool × model); the score is the deterministic "
              "pass rate across that skill's eval prompts.")
# One-line blurb per skill, shown as a blockquote under each section header.
# Sourced from each plugin's SKILL.md. Skills absent here render with no blurb.
SKILL_DESCRIPTIONS = {
    "hawkscan": "Configures HawkScan, runs a DAST scan against your running app, "
                "fixes the vulnerabilities it finds, and rescans to verify.",
    "api": "Queries the StackHawk platform API for findings, scan history, and "
           "security posture across your apps.",
    "stackhawk-data-seed": "Sets up checked-in seed data so authenticated scans "
                           "can reach non-trivial application paths.",
    "hawkscan-ci": "Wires HawkScan into your CI/CD pipeline — detects the provider "
                   "and writes the workflow file.",
}


def render_block(matrix: dict) -> str:
    """README badge block: an `## Eval Results` heading + intro, then one
    `### <skill>` section per skill (combos arrive pre-sorted by skill, then
    tool, then model). Each section carries a one-line `>` blurb (when the
    skill is known) followed by badge lines grouped one per tool, each an
    endpoint image linking to the capture-baseline runs page. Assumes
    matrix["combos"] originates from write_outputs - skill/tool/model segments
    are pre-validated there and used verbatim in URLs here."""
    link = f"https://github.com/{_REPO}/actions/workflows/capture-baseline.yml"
    lines = [BLOCK_START,
             f"<!-- generated by publish-eval-badges.yml from {matrix['tag']}"
             " - do not edit by hand -->",
             "",
             EVAL_HEADING,
             "",
             EVAL_INTRO]
    by_skill: dict[str, list[dict]] = {}
    for row in matrix["combos"]:
        by_skill.setdefault(row["skill"], []).append(row)
    for skill, skill_rows in by_skill.items():
        lines.append("")
        lines.append(f"### {skill}")
        desc = SKILL_DESCRIPTIONS.get(skill)
        if desc:
            lines.append("")
            lines.append(f"> {desc}")
        lines.append("")
        by_tool: dict[str, list[dict]] = {}
        for row in skill_rows:
            by_tool.setdefault(row["tool"], []).append(row)
        for tool, tool_rows in by_tool.items():
            badges = []
            for row in tool_rows:
                raw = (f"https://raw.githubusercontent.com/{_REPO}/badges/"
                       f"{row['skill']}/{row['tool']}/{row['model']}.json")
                img = f"https://img.shields.io/endpoint?url={quote(raw, safe='')}"
                alt = f"{skill} · {tool} · {display_model(row['model'])}"
                badges.append(f"[![{alt}]({img})]({link})")
            lines.append(" ".join(badges) + "  ")
    lines.append("")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def replace_block(readme_text: str, block: str) -> str:
    """Replace the marker-fenced region (markers inclusive) with `block`.
    Assumes exactly one marker pair; with multiples, first-found wins."""
    start = readme_text.find(BLOCK_START)
    end = readme_text.find(BLOCK_END)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"README is missing {BLOCK_START}/{BLOCK_END} markers")
    return readme_text[:start] + block + readme_text[end + len(BLOCK_END):]
