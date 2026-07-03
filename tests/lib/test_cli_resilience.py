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
    assert len(cell["results"]) == 24            # all hawkscan prompts graded
    # positive prompts failed with a harness note; at least one note mentions the crash
    assert any("command not found" in r.get("note", "") for r in cell["results"])
