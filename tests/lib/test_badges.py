import json

import pytest

from evals.lib.models import CellReport, EvalResult, Verdict
from evals.lib.badges import (
    BLOCK_END, BLOCK_START, SKILL_DESCRIPTIONS, aggregate, cell_ran, color_for,
    display_model, endpoint_json, render_block, replace_block, write_outputs,
)


def _result(run_id: str, verdict: Verdict, note: str = "") -> EvalResult:
    return EvalResult(platform="p", skill="s", run_id=run_id, should_trigger=True,
                      did_trigger=True, trigger_correct=True, verdict=verdict,
                      score=100, note=note)


def _cell(platform: str, skill: str, model: str, results: list[EvalResult]) -> CellReport:
    return CellReport(platform=platform, skill=skill, model=model, commit="abc1234",
                      results=results)


def _key(cell: CellReport):
    return (cell.platform, cell.skill, cell.model)


def _cells(*cells: CellReport) -> dict:
    return {_key(c): c for c in cells}


def test_cell_ran_true_when_any_result_has_no_note():
    cell = _cell("claude-code", "hawkscan", "m", [
        _result("a", Verdict.PASS),
        _result("b", Verdict.FAIL, note="harness launch failed"),
    ])
    assert cell_ran(cell) is True


def test_cell_ran_false_when_all_results_noted():
    cell = _cell("agy", "hawkscan", "default", [
        _result("a", Verdict.FAIL, note="agy OAuth wall"),
        _result("b", Verdict.FAIL, note="agy OAuth wall"),
    ])
    assert cell_ran(cell) is False


def test_cell_ran_false_when_no_results():
    assert cell_ran(_cell("agy", "hawkscan", "default", [])) is False


def test_aggregate_one_row_per_skill_tool_model():
    cells = _cells(
        _cell("claude-code", "hawkscan", "m1",
              [_result("a", Verdict.PASS), _result("b", Verdict.FAIL)]),
        _cell("claude-code", "api", "m1",
              [_result("c", Verdict.PASS), _result("d", Verdict.PASS_SLOW)]),
    )
    rows = aggregate(cells)
    assert rows == [
        {"skill": "hawkscan", "tool": "claude-code", "model": "m1",
         "passed": 1, "total": 2, "rate": 0.5, "status": "ok"},
        {"skill": "api", "tool": "claude-code", "model": "m1",
         "passed": 2, "total": 2, "rate": 1.0, "status": "ok"},
    ]


def test_aggregate_pass_slow_counts_as_pass():
    cells = _cells(_cell("codex", "hawkscan", "gpt-5.5", [_result("a", Verdict.PASS_SLOW)]))
    assert aggregate(cells)[0]["passed"] == 1


def test_aggregate_dead_cell_is_no_data():
    cells = _cells(_cell("agy", "hawkscan", "default",
                         [_result("a", Verdict.FAIL, note="oauth")]))
    assert aggregate(cells) == [
        {"skill": "hawkscan", "tool": "agy", "model": "default",
         "passed": 0, "total": 0, "rate": None, "status": "no-data"}]


def test_aggregate_noted_runs_excluded_from_rate():
    cells = _cells(
        _cell("claude-code", "hawkscan", "m1", [
            _result("a", Verdict.PASS),
            _result("b", Verdict.FAIL, note="harness launch flake"),
        ]),
    )
    assert aggregate(cells) == [
        {"skill": "hawkscan", "tool": "claude-code", "model": "m1",
         "passed": 1, "total": 1, "rate": 1.0, "status": "ok"}]


def test_aggregate_orders_by_skill_then_tool_then_model():
    cells = _cells(
        _cell("cursor", "api", "default", [_result("a", Verdict.PASS)]),
        _cell("claude-code", "hawkscan-ci", "z", [_result("b", Verdict.PASS)]),
        _cell("claude-code", "hawkscan", "claude-sonnet-4-6", [_result("c", Verdict.PASS)]),
        _cell("claude-code", "hawkscan", "claude-haiku-4-5-20251001", [_result("d", Verdict.PASS)]),
        _cell("codex", "hawkscan", "o3", [_result("e", Verdict.PASS)]),
        _cell("zz-tool", "hawkscan", "m", [_result("f", Verdict.PASS)]),
    )
    combos = [(r["skill"], r["tool"], r["model"]) for r in aggregate(cells)]
    assert combos == [
        ("hawkscan", "claude-code", "claude-haiku-4-5-20251001"),
        ("hawkscan", "claude-code", "claude-sonnet-4-6"),
        ("hawkscan", "codex", "o3"),
        ("hawkscan", "zz-tool", "m"),
        ("api", "cursor", "default"),
        ("hawkscan-ci", "claude-code", "z"),
    ]


def test_color_thresholds_at_boundaries():
    assert color_for(1.0) == "brightgreen"
    assert color_for(0.99) == "green"
    assert color_for(0.90) == "green"
    assert color_for(0.89) == "yellow"
    assert color_for(0.80) == "yellow"
    assert color_for(0.79) == "red"
    assert color_for(None) == "lightgrey"


def test_display_model_strips_claude_prefix_and_date_suffix():
    assert display_model("claude-sonnet-4-6") == "sonnet-4-6"
    assert display_model("claude-haiku-4-5-20251001") == "haiku-4-5"
    assert display_model("gpt-5.5") == "gpt-5.5"
    assert display_model("o3") == "o3"
    assert display_model("default") == "default"
    assert display_model("claude-haiku-4-5-202510") == "haiku-4-5"
    assert display_model("claude-") == "claude-"


def test_endpoint_json_ok_row():
    row = {"tool": "claude-code", "model": "claude-sonnet-4-6",
           "passed": 15, "total": 16, "rate": 15 / 16, "status": "ok"}
    assert endpoint_json(row) == {
        "schemaVersion": 1,
        "label": "claude-code · sonnet-4-6",
        "message": "93% (15/16)",
        "color": "green",
    }


def test_endpoint_json_floors_percent_so_only_perfect_shows_100():
    row = {"tool": "codex", "model": "gpt-5.5",
           "passed": 199, "total": 200, "rate": 199 / 200, "status": "ok"}
    assert endpoint_json(row)["message"] == "99% (199/200)"


def test_endpoint_json_no_data_row():
    row = {"tool": "agy", "model": "default", "passed": 0, "total": 0,
           "rate": None, "status": "no-data"}
    assert endpoint_json(row) == {
        "schemaVersion": 1,
        "label": "agy · default",
        "message": "no data",
        "color": "lightgrey",
    }


def test_write_outputs_creates_per_skill_tool_model_jsons_and_matrix(tmp_path):
    cells = _cells(
        _cell("claude-code", "hawkscan", "claude-sonnet-4-6", [_result("a", Verdict.PASS)]),
        _cell("agy", "api", "default", [_result("b", Verdict.FAIL, note="oauth")]),
    )
    matrix = write_outputs(cells, tmp_path, tag="v1.9.0",
                           run_url="https://github.com/stackhawk/agent-skills/actions/runs/1")

    badge = json.loads((tmp_path / "hawkscan" / "claude-code" / "claude-sonnet-4-6.json").read_text())
    assert badge["message"] == "100% (1/1)"
    assert badge["color"] == "brightgreen"

    nodata = json.loads((tmp_path / "api" / "agy" / "default.json").read_text())
    assert nodata["message"] == "no data"

    on_disk = json.loads((tmp_path / "matrix.json").read_text())
    assert on_disk == matrix
    assert on_disk["schema"] == 2
    assert on_disk["tag"] == "v1.9.0"
    assert on_disk["run_url"].endswith("/runs/1")
    assert [(c["skill"], c["tool"]) for c in on_disk["combos"]] == [
        ("hawkscan", "claude-code"), ("api", "agy")]


def test_write_outputs_raises_on_empty_cells(tmp_path):
    with pytest.raises(SystemExit, match="refusing to publish"):
        write_outputs({}, tmp_path, tag="v1.9.0", run_url="")


def test_write_outputs_rejects_path_escaping_segments(tmp_path):
    cells = _cells(
        _cell("claude-code", "../evil", "m", [_result("a", Verdict.PASS)]),
    )
    with pytest.raises(SystemExit, match="unsafe path segment"):
        write_outputs(cells, tmp_path, tag="v1", run_url="")


_MATRIX = {
    "schema": 2, "tag": "v1.9.0",
    "run_url": "https://github.com/stackhawk/agent-skills/actions/runs/1",
    "combos": [
        {"skill": "hawkscan", "tool": "claude-code", "model": "claude-sonnet-4-6",
         "passed": 15, "total": 16, "rate": 15 / 16, "status": "ok"},
        {"skill": "hawkscan", "tool": "claude-code", "model": "claude-opus-4-7",
         "passed": 16, "total": 16, "rate": 1.0, "status": "ok"},
        {"skill": "hawkscan", "tool": "agy", "model": "default",
         "passed": 0, "total": 0, "rate": None, "status": "no-data"},
        {"skill": "api", "tool": "codex", "model": "gpt-5.5",
         "passed": 8, "total": 10, "rate": 0.8, "status": "ok"},
    ],
}


def test_render_block_has_eval_results_heading_and_intro():
    block = render_block(_MATRIX)
    assert "## Eval Results" in block
    # intro mentions the per-skill breakdown
    assert "broken down by skill" in block


def test_render_block_skill_section_has_blockquote_description():
    block = render_block(_MATRIX)
    lines = block.splitlines()
    # the description blockquote sits between the skill header and its badges
    hawk_idx = lines.index("### hawkscan")
    quote_line = f"> {SKILL_DESCRIPTIONS['hawkscan']}"
    assert quote_line in lines[hawk_idx:]
    # and it appears before the first badge line of that section
    first_badge = next(i for i, line in enumerate(lines)
                       if i > hawk_idx and "img.shields.io" in line)
    assert lines.index(quote_line) < first_badge


def test_render_block_unknown_skill_renders_without_blockquote():
    matrix = {
        "schema": 2, "tag": "v0", "run_url": "",
        "combos": [{"skill": "mystery-skill", "tool": "claude-code", "model": "m",
                    "passed": 1, "total": 1, "rate": 1.0, "status": "ok"}],
    }
    block = render_block(matrix)
    assert "### mystery-skill" in block
    # no blockquote line for a skill with no description, and no crash
    section = block.split("### mystery-skill", 1)[1]
    assert not section.lstrip().startswith(">")


def test_render_block_emits_one_section_per_skill():
    block = render_block(_MATRIX)
    lines = block.splitlines()
    assert lines[0] == BLOCK_START
    assert lines[-1] == BLOCK_END
    assert block.count("### hawkscan") == 1
    assert block.count("### api") == 1


def test_render_block_section_has_per_tool_lines():
    block = render_block(_MATRIX)
    lines = block.splitlines()
    hawk_idx = lines.index("### hawkscan")
    api_idx = lines.index("### api")
    hawk_badge_lines = [line for line in lines[hawk_idx:api_idx] if "img.shields.io" in line]
    assert len(hawk_badge_lines) == 2          # claude-code line, agy line
    assert hawk_badge_lines[0].count("img.shields.io") == 2  # two claude-code models


def test_render_block_urlencodes_skill_scoped_raw_url():
    block = render_block(_MATRIX)
    assert ("img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com"
            "%2Fstackhawk%2Fagent-skills%2Fbadges%2Fhawkscan%2Fclaude-code"
            "%2Fclaude-sonnet-4-6.json") in block
    assert "https://github.com/stackhawk/agent-skills/actions/workflows/capture-baseline.yml" in block


def test_render_block_alt_text_includes_skill():
    block = render_block(_MATRIX)
    assert "[![api · codex · gpt-5.5]" in block


def test_render_block_rejects_path_escaping_segment_from_tampered_matrix():
    matrix = {
        "schema": 2, "tag": "v0", "run_url": "",
        "combos": [{"skill": "../evil", "tool": "claude-code", "model": "m",
                    "passed": 1, "total": 1, "rate": 1.0, "status": "ok"}],
    }
    with pytest.raises(SystemExit, match="unsafe path segment"):
        render_block(matrix)


def test_replace_block_swaps_marker_fenced_region():
    readme = f"# Title\n\n{BLOCK_START}\nold stuff\n{BLOCK_END}\n\nBody text.\n"
    out = replace_block(readme, render_block(_MATRIX))
    assert "old stuff" not in out
    assert "img.shields.io" in out
    assert out.startswith("# Title\n\n")
    assert out.endswith("\n\nBody text.\n")


def test_replace_block_is_idempotent():
    readme = f"# Title\n\n{BLOCK_START}\n{BLOCK_END}\n\nBody.\n"
    once = replace_block(readme, render_block(_MATRIX))
    twice = replace_block(once, render_block(_MATRIX))
    assert once == twice


def test_replace_block_raises_when_markers_missing():
    with pytest.raises(SystemExit):
        replace_block("# Title\n\nno markers here\n", render_block(_MATRIX))
