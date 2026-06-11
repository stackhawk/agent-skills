"""Pure-Python (no AI) comparison of a run against a baseline run."""
from __future__ import annotations
from pathlib import Path

from evals.lib.models import CellReport


def diff(current: CellReport, baseline: CellReport) -> dict[str, str]:
    cur = {r.run_id: r.verdict.value for r in current.results}
    base = {r.run_id: r.verdict.value for r in baseline.results}
    out: dict[str, str] = {}
    for rid in set(cur) | set(base):
        if rid not in base:
            out[rid] = "new"
        elif rid not in cur:
            out[rid] = "dropped"
        elif cur[rid] == base[rid]:
            out[rid] = "same"
        elif cur[rid] == "fail":
            out[rid] = "regressed"
        elif base[rid] == "fail":
            out[rid] = "fixed"
        else:
            out[rid] = "changed"
    return out


def score_delta(current_avg: int, baseline_avg: int, band: int = 3) -> str:
    d = current_avg - baseline_avg
    if abs(d) <= band:
        return "no-change"
    return "better" if d > 0 else "worse"


def load_baseline_dir(path: Path | None) -> dict[tuple[str, str, str], CellReport]:
    out: dict[tuple[str, str, str], CellReport] = {}
    if not path or not Path(path).exists():
        return out
    for cj in Path(path).rglob("cell.json"):
        try:
            cell = CellReport.model_validate_json(cj.read_text())
        except Exception:
            continue
        out[(cell.platform, cell.skill, cell.model)] = cell
    return out
