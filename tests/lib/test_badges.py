from evals.lib.models import CellReport, EvalResult, Verdict
from evals.lib.badges import aggregate, cell_ran, color_for, display_model, endpoint_json


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


def test_aggregate_pass_rate_across_skills():
    cells = _cells(
        _cell("claude-code", "hawkscan", "m1",
              [_result("a", Verdict.PASS), _result("b", Verdict.FAIL)]),
        _cell("claude-code", "api", "m1",
              [_result("c", Verdict.PASS), _result("d", Verdict.PASS_SLOW)]),
    )
    rows = aggregate(cells)
    assert rows == [{"tool": "claude-code", "model": "m1", "passed": 3, "total": 4,
                     "rate": 0.75, "status": "ok"}]


def test_aggregate_pass_slow_counts_as_pass():
    cells = _cells(_cell("codex", "hawkscan", "gpt-5.5", [_result("a", Verdict.PASS_SLOW)]))
    assert aggregate(cells)[0]["passed"] == 1


def test_aggregate_all_cells_dead_is_no_data():
    cells = _cells(
        _cell("agy", "hawkscan", "default", [_result("a", Verdict.FAIL, note="oauth")]),
        _cell("agy", "api", "default", []),
    )
    rows = aggregate(cells)
    assert rows == [{"tool": "agy", "model": "default", "passed": 0, "total": 0,
                     "rate": None, "status": "no-data"}]


def test_aggregate_dead_cells_excluded_from_live_combo_totals():
    cells = _cells(
        _cell("claude-code", "hawkscan", "m1", [_result("a", Verdict.PASS)]),
        _cell("claude-code", "api", "m1", [_result("b", Verdict.FAIL, note="launch failed")]),
    )
    rows = aggregate(cells)
    assert rows[0]["passed"] == 1
    assert rows[0]["total"] == 1


def test_aggregate_noted_runs_within_live_cell_excluded_from_rate():
    cells = _cells(
        _cell("claude-code", "hawkscan", "m1", [
            _result("a", Verdict.PASS),
            _result("b", Verdict.FAIL, note="harness launch flake"),
        ]),
    )
    rows = aggregate(cells)
    assert rows == [{"tool": "claude-code", "model": "m1", "passed": 1, "total": 1,
                     "rate": 1.0, "status": "ok"}]


def test_aggregate_orders_tools_canonically_then_models_alpha():
    cells = _cells(
        _cell("cursor", "hawkscan", "default", [_result("a", Verdict.PASS)]),
        _cell("zz-new-tool", "hawkscan", "m", [_result("b", Verdict.PASS)]),
        _cell("claude-code", "hawkscan", "claude-sonnet-4-6", [_result("c", Verdict.PASS)]),
        _cell("claude-code", "hawkscan", "claude-haiku-4-5-20251001", [_result("d", Verdict.PASS)]),
        _cell("codex", "hawkscan", "o3", [_result("e", Verdict.PASS)]),
    )
    combos = [(r["tool"], r["model"]) for r in aggregate(cells)]
    assert combos == [
        ("claude-code", "claude-haiku-4-5-20251001"),
        ("claude-code", "claude-sonnet-4-6"),
        ("codex", "o3"),
        ("cursor", "default"),
        ("zz-new-tool", "m"),
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
