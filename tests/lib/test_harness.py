# tests/lib/test_harness.py
import json
from evals.lib.harness import get_adapter
from evals.lib.models import ParsedRun

CC = get_adapter("claude-code")


def test_parse_stream_extracts_bash_and_text():
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "hawk scan"}},
            {"type": "text", "text": "scanning now"},
        ]}}),
        json.dumps({"type": "result", "result": "done", "cost_usd": 0.04}),
    ]
    run = CC.parse_stream("\n".join(lines))
    assert isinstance(run, ParsedRun)
    assert run.bash_commands == ["hawk scan"]
    assert "scanning now" in run.output_text
    assert run.cost_usd == 0.04


def test_detect_trigger_via_cli_signal():
    run = ParsedRun(bash_commands=["hawk scan --env test"])
    assert CC.detect_trigger(run, "hawkscan") is True


def test_detect_trigger_negative():
    run = ParsedRun(bash_commands=["echo hello"], output_text="nothing relevant")
    assert CC.detect_trigger(run, "hawkscan") is False
