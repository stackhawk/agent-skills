import json
from pathlib import Path
import pytest
import evals.cli as cli_mod


class BoomAdapter:
    platform = "boom"

    def cli_signals(self, s):
        return []

    def invocation_signals(self, s):
        return []

    def parse_stream(self, raw):
        from evals.lib.models import ParsedRun
        return ParsedRun()

    def detect_trigger(self, run, s):
        return False

    def launch(self, *a, **k):
        raise FileNotFoundError("agent: command not found")


def test_main_survives_launch_crash(monkeypatch, tmp_path):
    # Point results at a temp dir and force the boom adapter + a tiny prompt set.
    monkeypatch.setattr(cli_mod, "get_adapter", lambda p: BoomAdapter())
    monkeypatch.setattr(cli_mod, "RESULTS_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["evals", "--harness", "claude-code", "--skill", "hawkscan"])
    with pytest.raises(SystemExit):   # FP/FN cause sys.exit(1) — that's fine
        cli_mod.main()
    # The cell + summary were still written despite every launch crashing:
    out = tmp_path / "claude-code" / "results" / "hawkscan"
    assert (out / "cell.json").exists()
    assert (out / "summary.json").exists()
    cell = json.loads((out / "cell.json").read_text())
    assert len(cell["results"]) == 26            # all hawkscan prompts graded
    # positive prompts failed with a harness note; at least one note mentions the crash
    assert any("command not found" in r.get("note", "") for r in cell["results"])


class ClonedFailedAdapter:
    """Simulates a discovery cell whose target_repo clone failed: launch()
    returns (rather than raises) a ParsedRun with .error set and no
    DISCOVERY: block in the output."""
    platform = "claude-code"

    def cli_signals(self, s):
        return []

    def invocation_signals(self, s):
        return []

    def parse_stream(self, raw):
        from evals.lib.models import ParsedRun
        return ParsedRun()

    def detect_trigger(self, run, s):
        return False

    def launch(self, *a, **k):
        from evals.lib.models import ParsedRun
        return ParsedRun(output_text="", error="git clone failed: repository not found",
                         returncode=1)


def test_broken_cell_skips_judge_and_fails(monkeypatch, tmp_path):
    # M3: the answer_key branch must not call the (costly) claude judge when the
    # run already errored / produced no DISCOVERY: block. Prove it with a call
    # counter (not a side effect that could be swallowed identically either way)
    # -- the cell must still grade (and FAIL, since grade_discovery's own
    # `expected` checks won't be satisfied) without ever invoking the judge.
    calls = {"n": 0}

    def _counting_judge(*a, **k):
        calls["n"] += 1
        return []

    monkeypatch.setattr("evals.lib.rubric.judge_answer_key", _counting_judge)
    monkeypatch.setattr(cli_mod, "get_adapter", lambda p: ClonedFailedAdapter())
    monkeypatch.setattr(cli_mod, "RESULTS_ROOT", tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["evals", "--harness", "claude-code", "--skill", "hawkscan", "--id", "firefly-iii"],
    )
    # A single errored cell means 0/1 prompts "ran cleanly" (note is non-empty),
    # which is the pre-existing plumbing-failure exit -- unrelated to the judge
    # skip behavior under test here. The cell.json is still written first.
    with pytest.raises(SystemExit):
        cli_mod.main()
    assert calls["n"] == 0, "judge_answer_key must not be called for a broken cell"
    out = tmp_path / "claude-code" / "results" / "hawkscan"
    cell = json.loads((out / "cell.json").read_text())
    assert len(cell["results"]) == 1
    result = cell["results"][0]
    assert result["run_id"] == "firefly-iii"
    assert result["verdict"] == "fail"          # expected checks unmet -> FAIL as before
