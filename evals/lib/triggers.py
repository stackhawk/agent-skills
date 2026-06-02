"""Shared trigger-decision helpers used by every harness adapter.

The agents declare a decision line under the observe suffix, e.g.
`hawkscan:hawkscan: YES` or `none: NO`. That explicit declaration is the agent's
considered verdict and must be authoritative — it should not be overridden by the
looser behavioral phrases in INVOCATION_SIGNALS (e.g. "security scan after"), which
frequently appear because the agent is *quoting the user's negative instruction*
("Don't run a security scan after this change"). Treating the explicit decline as
authoritative removes that class of false positive.
"""
from __future__ import annotations
import re

# How the agent names each skill in its decision line. Full `plugin:skill` form
# first (most specific), then the bare skill name. Hyphens are literal here, so we
# never normalize them away (would corrupt `stackhawk-api`).
_DECL_NAMES = {
    "hawkscan": ["hawkscan:hawkscan", "hawkscan"],
    "api": ["stackhawk-api:api", "stackhawk-api"],
    "stackhawk-data-seed": ["stackhawk-data-seed:stackhawk-data-seed",
                            "stackhawk-data-seed"],
}

# Decision separator between the skill name and YES/NO: colon, hyphen, en/em dash.
_SEP = r"\s*[:\-–—]\s*"


def explicit_decision(text: str, skill: str) -> str | None:
    """Return 'yes'/'no' if the agent emitted an explicit decision line for `skill`
    (or a global `none: NO`), else None. Strips markdown emphasis first so
    `**hawkscan:hawkscan: YES**` and `` `none: NO` `` are recognized."""
    norm = re.sub(r"[*`_]+", "", text.lower())
    names = _DECL_NAMES.get(skill, [skill])

    def declared(name: str, verdict: str) -> bool:
        return re.search(re.escape(name) + _SEP + verdict + r"\b", norm) is not None

    if any(declared(n, "yes") for n in names):
        return "yes"
    if re.search(r"\bnone" + _SEP + r"no\b", norm) or any(declared(n, "no") for n in names):
        return "no"
    return None


def decide_trigger(*, executed_cli: bool, declared: str | None, loose_hit: bool) -> bool:
    """Combine the three trigger signals with the right precedence:
      1. Real CLI execution is unambiguous — the skill ran.
      2. An explicit decision line (YES/NO) is authoritative for narration.
      3. Otherwise fall back to loose behavioral phrase matches.
    """
    if executed_cli:
        return True
    if declared == "no":
        return False
    if declared == "yes":
        return True
    return loose_hit
