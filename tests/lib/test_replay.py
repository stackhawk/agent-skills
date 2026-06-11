# tests/lib/test_replay.py
from pathlib import Path
from evals.lib.replay import regrade
from evals.lib.models import Verdict

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hw-07.trace.jsonl"


def test_regrade_from_trace_passes():
    result = regrade(FIXTURE, skill="hawkscan", platform="claude-code")
    assert result.did_trigger is True
    assert result.verdict in (Verdict.PASS, Verdict.PASS_SLOW)
    assert result.run_id == "hw-07"


def test_regrade_is_deterministic():
    a = regrade(FIXTURE, skill="hawkscan", platform="claude-code")
    b = regrade(FIXTURE, skill="hawkscan", platform="claude-code")
    assert a.verdict == b.verdict
    assert a.score == b.score
