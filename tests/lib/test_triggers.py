"""Tests for the shared trigger-decision helpers (evals/lib/triggers.py).

The motivating bug: hw-17 ("Don't run a security scan after this change — just
commit it") is a negative. The agent correctly declared `hawkscan:hawkscan: NO`,
but detect_trigger substring-matched the loose phrase "security scan after" from
the agent quoting the user's instruction, producing a false positive.
"""
from evals.lib.triggers import explicit_decision, decide_trigger


def test_explicit_yes_recognized():
    assert explicit_decision("hawkscan:hawkscan: YES — run a scan", "hawkscan") == "yes"
    assert explicit_decision("**stackhawk-api:api: YES**", "api") == "yes"
    assert explicit_decision("`stackhawk-data-seed:stackhawk-data-seed: YES`",
                             "stackhawk-data-seed") == "yes"


def test_explicit_no_recognized():
    assert explicit_decision("hawkscan:hawkscan: NO — user declined", "hawkscan") == "no"
    assert explicit_decision("Decision: none: NO", "hawkscan") == "no"
    assert explicit_decision("stackhawk-api:api — NO", "api") == "no"


def test_dash_and_emphasis_separators():
    assert explicit_decision("**hawkscan:hawkscan — YES**", "hawkscan") == "yes"
    assert explicit_decision("hawkscan:hawkscan - NO", "hawkscan") == "no"


def test_no_decision_line_returns_none():
    assert explicit_decision("I'll run a security scan for you.", "hawkscan") is None


def test_hyphenated_skill_name_not_corrupted():
    # `stackhawk-api` must not be mis-split on its internal hyphen.
    assert explicit_decision("stackhawk-api:api: NO", "api") == "no"
    assert explicit_decision("stackhawk-data-seed:stackhawk-data-seed: NO",
                             "stackhawk-data-seed") == "no"


def test_hw17_false_positive_suppressed():
    # The exact failure mode: explicit decline + a loose phrase the agent quoted.
    text = ("**hawkscan:hawkscan: NO** — User explicitly requested "
            '"Don\'t run a security scan after this change"\n\n**Decision: none: NO**')
    declared = explicit_decision(text, "hawkscan")
    assert declared == "no"
    # Even though a loose behavioral phrase matched, the explicit decline wins.
    assert decide_trigger(executed_cli=False, declared=declared, loose_hit=True) is False


def test_real_execution_overrides_declared_no():
    # If the agent actually ran the CLI, it triggered regardless of what it said.
    assert decide_trigger(executed_cli=True, declared="no", loose_hit=False) is True


def test_loose_fallback_when_no_decision():
    assert decide_trigger(executed_cli=False, declared=None, loose_hit=True) is True
    assert decide_trigger(executed_cli=False, declared=None, loose_hit=False) is False


def test_explicit_yes_triggers_without_loose():
    assert decide_trigger(executed_cli=False, declared="yes", loose_hit=False) is True


def test_does_not_apply_is_decline():
    assert explicit_decision("`hawkscan:hawkscan` does not apply here", "hawkscan") == "no"
    assert explicit_decision("the api skill is not needed: stackhawk-api:api not applicable", "api") == "no"


def test_choosing_a_different_skill_declines_this_one():
    # hw-13: agent picks api, says hawkscan doesn't apply — must not be a hawkscan trigger.
    txt = "`stackhawk-api:api: YES`\n(`hawkscan:hawkscan` does not apply — you asked for findings.)"
    assert explicit_decision(txt, "hawkscan") == "no"
    assert explicit_decision(txt, "api") == "yes"


def test_other_skill_yes_alone_declines():
    assert explicit_decision("hawkscan:hawkscan: YES", "api") == "no"
    assert explicit_decision("hawkscan:hawkscan: YES", "stackhawk-data-seed") == "no"


def test_own_yes_not_suppressed_by_other():
    # Both declared yes — this skill is still yes.
    txt = "stackhawk-api:api: YES and hawkscan:hawkscan: YES"
    assert explicit_decision(txt, "hawkscan") == "yes"
