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


def test_mapping_requires_the_enabled_flag() -> None:
    """The BOLA/BFLA plugin entries must be written with `enabled: true`.

    Origin: a clean-room LiteLLM session did everything right — stated the
    `multi-role` verdict, wrote three profiles, added 422004/422005 literally,
    upserted the policy, scanned with --all-plugins-per-profile — and still got
    zero authorization coverage, because the hand-built entries omitted
    `enabled`. The platform stored both plugins *disabled*.

    In the base policy JSON, `enabled` is only ever `true` (96/165 entries) or
    absent (69/165) — never explicitly `false`. That is proto3 default omission:
    `enabled: false` serializes to nothing, so **absent means disabled**. An
    agent copying entry shape from a neighbouring base plugin (pluginId 0,
    `Directory Browsing`, which has no `enabled` key) produces a disabled entry.

    So naming the plugin IDs is not sufficient instruction; the entry shape has
    to be spelled out.
    """
    mapping = (REPO / "plugins/optimize/skills/optimize/references/mapping.md").read_text()
    section = _section(mapping, r"^### Multi-role apps", r"^## |\Z")
    assert '"enabled": true' in section, (
        "mapping.md does not tell the agent to set `enabled: true` on the "
        "BOLA/BFLA entries — omitting the field stores them DISABLED"
    )
    assert re.search(r"absent|omit", section, re.IGNORECASE), (
        "mapping.md does not warn that an omitted `enabled` field means "
        "disabled, which is the trap that produced zero coverage"
    )


def test_trust_is_defined_as_enabled_not_merely_present() -> None:
    """hawkscan's trust statement must mean 'enabled', not 'present'.

    The provenance gate passes the flag on the strength of optimize's guarantee.
    If that guarantee is only 'the policy contains 422004/422005', a policy with
    both plugins present-but-disabled satisfies it while testing nothing.
    """
    # Scope to the section explaining when policy contents still decide coverage.
    # Matching "enabled" anywhere in the file is not enough: a status-line
    # template once read "(BOLA/BFLA enabled)", unrelated to the plugin flag,
    # and produced a false pass here.
    #
    # Under primary-full the engine supplies BOLA/BFLA to non-primary profiles,
    # so the guarantee is no longer load-bearing for the default path — but it
    # still is for all-full and for offline runs, and that is what this asserts.
    section = _section(AUTHZ.read_text(), r"^## Why this is not automatic", r"^## ")
    assert "422004" in section, "the section does not state the guarantee"
    assert re.search(r"\benabled\b", section), (
        "the trust statement says the policy must *contain* 422004/422005 but "
        "never that they must be ENABLED — a present-but-disabled pair "
        "satisfies it while testing nothing"
    )


def test_no_skill_instructs_policy_get_on_an_org_policy() -> None:
    """`hawk op policy get` resolves StackHawk presets only, never org policies.

    Root cause in hawkop (`client/stackhawk.rs:2769`): `get_policy(name)` issues
    `GET /policy?policyName=<name>` with no org scoping, while org policies live
    behind the org-scoped `GET /policy/{org_id}/list`. Its siblings
    `upsert_org_policy` / `delete_org_policy` both require an org_id; `get` does
    not. Verified against a live org: DEFAULT and DEFAULT_API return policies,
    while MY_API, LONG_SCAN and OPTIMIZE_TRIAL_LITELLM_DEVELOPMENT all return
    "Error: Resource not found" despite appearing in `policy list`.

    So any instruction telling an agent to fetch an OPTIMIZE_* (org) policy by
    name is dead on arrival. Fetching a PRESET by name is fine and stays allowed.
    """
    offenders = []
    for md in sorted((REPO / "plugins").rglob("*.md")):
        for i, line in enumerate(md.read_text().splitlines(), 1):
            if "policy get" not in line:
                continue
            # Preset fetches are legitimate; so is prose documenting that the
            # command cannot read org policies.
            if re.search(r"PRESET|DEFAULT|preset", line):
                continue
            if re.search(r"cannot|can't|not\b.*fetch|broken|only presets", line, re.IGNORECASE):
                continue
            if re.search(r"OPTIMIZE|org polic|trial polic", line, re.IGNORECASE):
                offenders.append(f"{md.relative_to(REPO)}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "these instructions fetch an org policy by name, which always fails:\n  "
        + "\n  ".join(offenders)
    )


def _skill_markdown() -> dict[str, str]:
    """Every shipped skill markdown file, keyed by repo-relative path."""
    return {str(p.relative_to(REPO)): p.read_text()
            for p in sorted((REPO / "plugins").rglob("*.md"))}


def test_dead_flag_is_gone_everywhere() -> None:
    """`--all-plugins-per-profile` was replaced, not deprecated.

    The local hawk build exposes `--profile-scan-mode=(business-logic|
    primary-full|all-full)` and `hawk scan --help` no longer mentions the old
    flag at all. Any instruction still naming it tells an agent to pass an
    argument the binary rejects.
    """
    offenders = [f"{path}" for path, text in _skill_markdown().items()
                 if "all-plugins-per-profile" in text]
    assert not offenders, (
        "these files reference the removed --all-plugins-per-profile flag: "
        + ", ".join(offenders)
    )


def test_primary_full_is_the_default_mode() -> None:
    """The skill must default to primary-full, not the engine default.

    `--profile-scan-mode` defaults to `business-logic` (BOLA/BFLA only, every
    profile). Passing nothing therefore gives a 2-plugin scan. primary-full runs
    the full policy on one profile and BOLA/BFLA on the rest.
    """
    authz = AUTHZ.read_text()
    assert "--profile-scan-mode=primary-full" in authz, (
        "authz-profiles.md does not name the default mode the skill should pass"
    )
    assert re.search(r"business-logic.*default|default.*business-logic", authz, re.IGNORECASE), (
        "the doc does not warn that the flag's own default is business-logic, "
        "so omitting it silently yields a 2-plugin scan"
    )


def test_full_scan_profile_is_named_explicitly() -> None:
    """--full-scan-profile must be pinned to the privileged profile.

    It defaults to the first profile declared in the config, which for us is a
    low-privilege peer — so relying on the default makes coverage depend on the
    order the skill happened to write profiles in.
    """
    authz = AUTHZ.read_text()
    assert "--full-scan-profile" in authz, "the flag is never mentioned"
    section = _section(authz, r"--full-scan-profile", r"^## ")
    assert re.search(r"privileg|admin", section, re.IGNORECASE), (
        "the doc does not say to pin --full-scan-profile to the privileged "
        "profile; falling back to declaration order scans as a peer"
    )


def test_attribution_is_other_info_not_evidence() -> None:
    """Profile attribution lives in Other Info, not the evidence string.

    hawkscan moved it (commit 4bd23cf86): the platform UI highlights a finding by
    locating the evidence string verbatim inside the captured request/response,
    so prefixing evidence with [profile=<name>] silently broke highlighting.
    A doc still telling an agent to parse evidence sends it to the wrong field.
    """
    section = _section(AUTHZ.read_text(), r"^## Reading per-profile findings", r"^## |\Z")
    assert re.search(r"other info", section, re.IGNORECASE), (
        "the attribution section does not name Other Info as the field"
    )
    assert not re.search(r"prefix.{0,40}evidence|evidence.{0,40}prefix", section, re.IGNORECASE), (
        "the attribution section still describes an evidence prefix, which no "
        "longer exists and would send an agent to the wrong field"
    )


def test_offline_bola_bfla_gap_is_documented() -> None:
    """Keyless/offline runs get no BOLA/BFLA on non-primary profiles.

    `policyForProfile` falls back to the bundled full policy when `!canSend()`,
    and 422004/422005 exist in no bundled policy — so the engine's BOLA/BFLA
    guarantee quietly does not hold without platform connectivity.
    """
    authz = AUTHZ.read_text()
    assert re.search(r"offline|keyless|no platform|without.{0,20}platform", authz, re.IGNORECASE), (
        "the offline fallback is undocumented, so an agent will assume the "
        "engine supplies BOLA/BFLA when it cannot"
    )


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
