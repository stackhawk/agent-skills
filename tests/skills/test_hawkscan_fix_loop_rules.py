"""The hawkscan fix loop must have one bounded rule that always ends on a rescan.

SKILL.md once said both "Repeat until exit 0" (unbounded) and "Max one fix-rescan
cycle" (capped, with no rescan required after the last fix). An autonomous run could
satisfy both by fixing the first rescan's findings and stopping, leaving the fixes
unverified. These checks cover every shipped copy: the source skill, the generated
wingman/Copilot bundle and the generated Cursor rules.

This is a phrase lock on vocabulary, not a test of loop semantics. A deliberate
rewording of the rule should update it. It is not run in PR CI.
"""
import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_DIRS = [
    "plugins/hawkscan/skills/hawkscan",
    "plugins/wingman/copilot-skills/hawkscan",
]
CURSOR = "cursor/.cursor/rules"

# Each SKILL.md copy. Cursor rule-only installs get SKILL.md but not
# autonomous-loop.md, so SKILL.md must carry the whole rule itself.
SKILL_MD = [f"{d}/SKILL.md" for d in SKILL_DIRS] + [f"{CURSOR}/stackhawk-hawkscan.mdc"]
AUTONOMOUS_LOOP = [f"{d}/references/autonomous-loop.md" for d in SKILL_DIRS]
CROSS_REFS = (
    [f"{d}/references/high-iteration-findings.md" for d in SKILL_DIRS]
    + [f"{d}/references/scan-quality.md" for d in SKILL_DIRS]
    + [f"{d}/references/platform-model.md" for d in SKILL_DIRS]
    + [
        f"{CURSOR}/stackhawk-hawkscan-high-iteration.mdc",
        f"{CURSOR}/stackhawk-hawkscan-scan-quality.mdc",
        f"{CURSOR}/stackhawk-hawkscan-model.mdc",
    ]
)
ALL_COPIES = SKILL_MD + AUTONOMOUS_LOOP + CROSS_REFS

# "one-cycle" is platform-model.md's paraphrase of the old guard rail.
OLD_RULES = [r"Repeat until exit 0", r"fix-rescan cycle", r"one-cycle"]


def read(rel):
    with open(os.path.join(REPO_ROOT, rel)) as f:
        return f.read()


@pytest.mark.parametrize("rel", ALL_COPIES)
@pytest.mark.parametrize("pattern", OLD_RULES)
def test_old_loop_rules_are_gone(rel, pattern):
    hits = [
        f"{rel}:{n}: {line.strip()}"
        for n, line in enumerate(read(rel).splitlines(), 1)
        if re.search(pattern, line, re.IGNORECASE)
    ]
    assert not hits, f"old loop rule {pattern!r} still shipped:\n" + "\n".join(hits)


@pytest.mark.parametrize("rel", SKILL_MD + AUTONOMOUS_LOOP)
def test_loop_ends_on_a_rescan(rel):
    assert "never on an edit" in read(rel), f"{rel} does not say the loop ends on a rescan, never on an edit"


@pytest.mark.parametrize("rel", SKILL_MD + AUTONOMOUS_LOOP)
def test_leftovers_at_cap_are_reported_unfixed(rel):
    assert re.search(r"\bunfixed\b", read(rel)), f"{rel} does not say findings left at the cap are reported as unfixed"


@pytest.mark.parametrize("rel", SKILL_MD + AUTONOMOUS_LOOP)
def test_failed_verifying_scan_is_reported_unverified(rel):
    assert re.search(r"\bunverified\b", read(rel)), f"{rel} does not say edits whose verifying scan failed are unverified"


@pytest.mark.parametrize("rel", SKILL_MD)
def test_skill_md_rule_lines_agree_on_one_fix_pass(rel):
    lines = read(rel).splitlines()
    exit_42 = [l for l in lines if "**Exit code 42**" in l]
    summary = [l for l in lines if l.startswith("- Fix-verify cap")]
    assert len(exit_42) == 1 and len(summary) == 1, f"{rel}: expected one exit-42 line and one guard-rail summary line"
    for line in exit_42 + summary:
        assert "one fix pass" in line, f"{rel}: rule line does not say 'one fix pass': {line.strip()}"


@pytest.mark.parametrize("rel", CROSS_REFS)
def test_cross_refs_name_the_fix_verify_cap(rel):
    assert re.search(r"fix-verify cap", read(rel), re.IGNORECASE), f"{rel} does not cite the fix-verify cap"


def test_skill_md_body_stays_within_best_practice_limit():
    # Mirrors generate-and-validate.yml: >500 body lines warns, >600 fails.
    content = read(f"{SKILL_DIRS[0]}/SKILL.md")
    fm = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    assert fm, "SKILL.md has no frontmatter"
    assert content[fm.end():].count("\n") <= 500
