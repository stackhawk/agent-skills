from evals.lib.observe import observe_suffix, OBSERVE_SUFFIX


def test_hawkscan_ci_suffix_present_and_specific():
    s = observe_suffix("hawkscan-ci")
    assert s, "hawkscan-ci must have an observe suffix"
    # declares the skill token
    assert "hawkscan-ci:hawkscan-ci: YES" in s
    # bakes in the don't-take-action boundary
    low = s.lower()
    assert "do not" in low
    assert "trigger the pipeline" in low or "push" in low
    # asks for the pipeline block it would write
    assert "pipeline" in low or "workflow" in low


def test_unknown_skill_suffix_empty():
    assert observe_suffix("nope") == ""
