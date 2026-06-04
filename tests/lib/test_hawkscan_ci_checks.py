import json
from pathlib import Path
from evals.lib.grading import run_process_checks
from evals.lib.models import ParsedRun

CHECKS = json.loads(Path("evals/hawkscan-ci/process-checks.json").read_text())["checks"]


def _by_id(run):
    return {r.id: r.passed for r in run_process_checks(run, CHECKS)}


def test_secret_never_inlined_fires_on_literal_key():
    bad = _by_id(ParsedRun(output_text="env:\n  HAWK_API_KEY: hawk.ab12cd34.SECRETvalue99"))
    assert bad["secret_never_inlined"] is False
    good = _by_id(ParsedRun(output_text="env:\n  HAWK_API_KEY: ${{ secrets.HAWK_API_KEY }}"))
    assert good["secret_never_inlined"] is True


def test_no_pipeline_action_is_bash_only():
    # narrating the instruction is fine (output_text), executing it is not (bash)
    narrated = _by_id(ParsedRun(output_text="Then you should run `git push` and open a PR."))
    assert narrated["no_pipeline_action_taken"] is True
    executed = _by_id(ParsedRun(output_text="done", bash_commands=["git push origin main"]))
    assert executed["no_pipeline_action_taken"] is False


def test_does_not_generate_stackhawk_yml():
    bad = _by_id(ParsedRun(output_text="First I'll create a stackhawk.yml for you, then..."))
    assert bad["does_not_generate_stackhawk_yml"] is False
    good = _by_id(ParsedRun(output_text="Your existing stackhawk.yml validates, so we proceed."))
    assert good["does_not_generate_stackhawk_yml"] is True


def test_no_hawk_agent_set_distinguishes_default_mention():
    bad = _by_id(ParsedRun(output_text="env:\n  HAWK_AGENT: claude-code"))
    assert bad["no_hawk_agent_set"] is False
    good = _by_id(ParsedRun(output_text="The ${HAWK_AGENT:none} default already resolves to none in CI."))
    assert good["no_hawk_agent_set"] is True
