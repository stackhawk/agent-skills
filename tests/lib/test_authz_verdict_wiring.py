"""Regression tests for the multi-role authorization verdict wiring.

Origin: a clean-room session against LiteLLM (a textbook multi-role target —
`proxy_admin`/`internal_user` roles, `/user/info`, `/team/update`) went through
Step 2a -> Phase 1c -> `hawk validate auth` and never once computed the
`multi-role` verdict, never opened `authz-profiles.md`, and wrote zero
`profiles:` entries. The skill content was installed and correct.

Root cause: the verdict was a trailing subordinate clause ("Also compute the
multi-role verdict") with no required output and no downstream checkpoint, so a
verdict that was NEVER COMPUTED was indistinguishable from a verdict of
"not multi-role". Phase 1c.7 therefore evaluated to "skip" and said nothing —
a silent fail-closed, the exact defect class the feature exists to prevent.

These tests assert the structural invariants that make that failure mode
impossible. They are deliberately about *enforceability*, not wording:

  1. The verdict is a BINARY required output — the skill must name both
     outcomes, so the agent must emit one of them. A vocabulary with only
     `multi-role` and no negative value is what let "absent" read as "negative".
  2. A checkpoint exists at Phase 1c, where the verdict becomes actionable.
  3. Step 2b (the retest path) reaches the verdict too, so an existing
     stackhawk.yml does not silently bypass authorization scanning.

Runs under pytest in CI, or standalone via `command python3 <this file>`
(the repo's `python3` alias points at a missing interpreter on some machines).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "plugins/hawkscan/skills/hawkscan/SKILL.md"
AUTHZ = REPO / "plugins/hawkscan/skills/hawkscan/references/authz-profiles.md"
CHECKS = REPO / "evals/hawkscan/process-checks.json"

BODY_LIMIT = 500  # CI warns above this; keep headroom for the next change.


def _body(path: Path) -> str:
    """Everything after the closing --- of the YAML frontmatter."""
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return text[m.end():] if m else text


def _section(text: str, start_pat: str, end_pat: str) -> str:
    """Text between two headings, exclusive of the end heading."""
    s = re.search(start_pat, text, re.MULTILINE)
    assert s, f"section start not found: {start_pat}"
    rest = text[s.end():]
    e = re.search(end_pat, rest, re.MULTILINE)
    return rest[: e.start()] if e else rest


def test_verdict_is_a_binary_required_output() -> None:
    """Both verdict values must be named in SKILL.md.

    With only `multi-role` in the vocabulary there is no way to tell "discovery
    ran and found no roles" from "discovery never looked" — the ambiguity that
    caused the LiteLLM miss. Naming a negative value forces the agent to emit
    one of two answers rather than optionally mentioning one.
    """
    body = _body(SKILL)
    assert "multi-role" in body, "positive verdict value missing from SKILL.md"
    assert "single-role" in body, (
        "negative verdict value `single-role` is absent, so a verdict that was "
        "never computed is indistinguishable from 'no roles found'"
    )


def test_step_1a_states_the_verdict_as_required() -> None:
    """Step 1a must mark the verdict as required output, not an optional aside."""
    step1a = _section(_body(SKILL), r"^### Step 1a: Discover What to Scan",
                      r"^### Step 1c:")
    assert "multi-role" in step1a, "Step 1a never mentions the verdict"
    # The obligation must attach to the verdict itself. Matching "required"
    # anywhere in the section is not enough — Step 1a already says the discovery
    # summary is "required before the first scan", which is a different claim and
    # produced a false pass on the first run of this test.
    verdict_lines = [ln for ln in step1a.splitlines()
                     if "multi-role" in ln or "single-role" in ln]
    assert verdict_lines, "no line states the verdict"
    window = " ".join(verdict_lines)
    assert re.search(r"\b(must|required)\b", window, re.IGNORECASE), (
        "the obligation is not attached to the verdict itself — an "
        "'Also compute ...' aside is what got skipped under load"
    )


def test_phase_1c_has_a_verdict_checkpoint() -> None:
    """Phase 1c is where roles become actionable; it must consult the verdict.

    Discovery is the producer, but if discovery is rushed the only remaining
    chance to catch it is here, while auth is being configured.
    """
    phase1c = _section(_body(SKILL), r"^### Phase 1c: Authentication Configuration",
                       r"^### Phase 1c\.5:")
    assert re.search(r"multi-role|single-role", phase1c), (
        "Phase 1c has no verdict checkpoint, so a verdict skipped during "
        "discovery is never caught before credentials are written"
    )


def test_step_2b_reaches_the_verdict() -> None:
    """The retest path must not silently bypass authorization scanning.

    Phase 1c.7 lives under Step 2a (generate from scratch). A repo that already
    has a stackhawk.yml routes to Step 2b, which previously never mentioned the
    verdict, 1c.7, or profiles — a second silent-skip path.
    """
    step2b = _section(_body(SKILL), r"^## Step 2b: Tune Existing",
                      r"^## Step 3:")
    assert re.search(r"multi-role|single-role|1c\.7", step2b), (
        "Step 2b never reaches the verdict, so retests against an existing "
        "stackhawk.yml skip authorization scanning entirely"
    )


def test_process_check_grades_the_verdict() -> None:
    """CI must grade the behavior, not just the prose.

    The structural tests above prove the instruction is enforceable; this proves
    the eval harness will actually catch an agent that ignores it.
    """
    checks = json.loads(CHECKS.read_text())["checks"]
    ids = {c["id"] for c in checks}
    assert "step1_multirole_verdict_stated" in ids, (
        "no process check grades whether the agent stated a verdict; without it "
        "CI cannot detect a silent skip like the LiteLLM run"
    )
    check = next(c for c in checks if c["id"] == "step1_multirole_verdict_stated")
    assert check["signals"], "check has no signals to match"
    assert check.get("severity") in {"blocking", "warning"}, "bad severity"


def test_skill_body_within_limit() -> None:
    """Guard the budget these edits had to fit inside."""
    n = _body(SKILL).count("\n")
    assert n <= BODY_LIMIT, f"SKILL.md body is {n} lines (limit {BODY_LIMIT})"


def test_authz_reference_is_reachable() -> None:
    """A reference nothing links to is a reference nobody reads."""
    assert AUTHZ.exists(), "authz-profiles.md is missing"
    assert "authz-profiles.md" in _body(SKILL), (
        "authz-profiles.md is not linked from SKILL.md"
    )


if __name__ == "__main__":
    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures.append(name)
                print(f"FAIL  {name}\n        {e}")
    print(f"\n{len(failures)} failed")
    raise SystemExit(1 if failures else 0)
