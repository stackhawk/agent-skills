from evals.lib.observe import observe_suffix, OBSERVE_SUFFIX


def test_hawkscan_ci_suffix_present_and_specific():
    s = observe_suffix("hawkscan-ci")
    assert s, "hawkscan-ci must have an observe suffix"
    # assert on body-specific text (the shared header already contains the YES token,
    # so checking for it wouldn't prove the hawkscan-ci entry exists)
    low0 = s.lower()
    assert "pipeline block" in low0
    assert "hand off to the hawkscan skill" in low0
    # bakes in the don't-take-action boundary
    low = s.lower()
    assert "do not" in low
    assert "trigger the pipeline" in low or "push" in low
    # asks for the pipeline block it would write
    assert "pipeline" in low or "workflow" in low


def test_unknown_skill_suffix_empty():
    assert observe_suffix("nope") == ""
