from pathlib import Path
from evals.lib.harness import get_adapter
from evals.lib.models import ParsedRun

FIX = Path(__file__).parent.parent / "fixtures" / "streams"


def test_codex_parse_stream():
    cx = get_adapter("codex")
    run = cx.parse_stream((FIX / "codex.txt").read_text())
    assert isinstance(run, ParsedRun)
    assert "hawk validate config stackhawk.yml" in run.bash_commands
    assert "hawk scan --env Development" in run.bash_commands
    assert "localhost:8080" in run.output_text
    assert run.output_tokens == 340


def test_codex_detect_trigger():
    cx = get_adapter("codex")
    run = ParsedRun(bash_commands=["hawk scan --env Development"])
    assert cx.detect_trigger(run, "hawkscan") is True
    assert cx.detect_trigger(ParsedRun(bash_commands=["echo hi"]), "hawkscan") is False


def test_cursor_parse_stream():
    cu = get_adapter("cursor")
    run = cu.parse_stream((FIX / "cursor.txt").read_text())
    assert "hawk scan --env Development" in run.bash_commands
    assert "localhost:8080" in run.output_text


def test_cursor_detect_trigger():
    cu = get_adapter("cursor")
    assert cu.detect_trigger(ParsedRun(bash_commands=["hawk scan x"]), "hawkscan") is True
