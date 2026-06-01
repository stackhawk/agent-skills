import importlib.util
from pathlib import Path
from evals.lib.harness import get_adapter
from evals.lib.models import ParsedRun

FIX = Path(__file__).parent.parent / "fixtures" / "streams"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_adapter_module(platform: str):
    path = REPO_ROOT / "evals" / "harnesses" / platform / "adapter.py"
    spec = importlib.util.spec_from_file_location(f"_t_adapter_{platform}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_agy_parse_stream_is_plaintext():
    ag = get_adapter("agy")
    run = ag.parse_stream((FIX / "agy.txt").read_text())
    assert run.bash_commands == []
    assert "hawk scan --env Development" in run.output_text


def test_agy_detect_trigger_via_text():
    ag = get_adapter("agy")
    run = ag.parse_stream((FIX / "agy.txt").read_text())
    assert ag.detect_trigger(run, "hawkscan") is True


def test_claude_code_parses_total_cost_usd():
    import json
    cc = get_adapter("claude-code")
    lines = [
        json.dumps({"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}),
        json.dumps({"type":"result","result":"done","total_cost_usd":0.123,"subtype":"success"}),
    ]
    run = cc.parse_stream("\n".join(lines))
    assert abs(run.cost_usd - 0.123) < 1e-9


def test_agy_observe_suffix_and_skill_signal():
    ag = get_adapter("agy")
    # The pre-shim SKILL: declaration format (emitted because of OBSERVE_SUFFIX)
    # must still be detected by detect_trigger.
    run = ag.parse_stream("I would use SKILL: hawkscan for this task.")
    assert ag.detect_trigger(run, "hawkscan") is True
    # OBSERVE_SUFFIX must be present, non-empty, and request the SKILL: declaration.
    mod = _load_adapter_module("agy")
    assert mod.OBSERVE_SUFFIX.strip()
    assert "SKILL: hawkscan" in mod.OBSERVE_SUFFIX
