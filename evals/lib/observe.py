"""Shared per-skill observe-mode prompt suffixes, used by every harness adapter.

Observe mode gauges whether the right skill TRIGGERS and whether the agent knows
its WORKFLOW, so we ask it to declare the skill and write out the commands it would
run. The declaration matches the explicit-decision parser (evals/lib/triggers.py);
the commands match the process-check signals (which scan bash_commands +
output_text). We deliberately do NOT list the commands here — producing them is the
skill's job, i.e. the test.

The suffix is PER-SKILL: the three skills have different sandbox execution
profiles, so one shared string can't serve all of them.
  - hawkscan needs a live target to scan. With none present, any execution attempt
    stalls mid-workflow, so its observe pass is a pure paper walkthrough.
  - api is a read-workflow over hawkop; it degrades gracefully (narrate if creds
    absent, run the read-only queries if present).
  - data-seed's product is the artifacts it emits (manifest + data-seed/), so its
    walkthrough must enumerate those.

Every harness shares this config and the same `plugin:skill: YES`/`none: NO`
decision format, so trigger detection is uniform across harnesses. Appended only
in observe mode — full-auto / extended runs against a real target use the bare
prompt.
"""
from __future__ import annotations

_OBSERVE_HEADER = (
    "\n\n---\n"
    "(Eval harness — observe mode. The target app, credentials, or prior scans may "
    "be unavailable here. Do NOT stop to ask for a target or for missing code. "
    "Output exactly:\n"
    "1. A decision line naming the StackHawk skill this request should invoke, "
    "written exactly as `hawkscan:hawkscan: YES`, `stackhawk-api:api: YES`, "
    "`stackhawk-data-seed:stackhawk-data-seed: YES`, or `none: NO`.\n"
)

OBSERVE_SUFFIX = {
    # hawkscan: no live target here, so executing the scan stalls — keep it a
    # pure paper walkthrough of the full command sequence.
    "hawkscan": _OBSERVE_HEADER + (
        "2. If (and only if) the hawkscan skill applies, write out its COMPLETE "
        "documented workflow as the exact CLI commands it runs, in order — every "
        "phase from preflight through the verifying rescan. This is a paper "
        "walkthrough: do NOT try to run the scan, there is no live target here. "
        "Pull the real commands straight from the skill (with their flags); do not "
        "summarize them and do not invent them.)"
    ),
    # api: a read-workflow over hawkop. Narrate the full command sequence; if
    # hawkop + credentials happen to be present, the read-only queries may also run.
    "api": _OBSERVE_HEADER + (
        "2. If (and only if) the api skill applies, write out its COMPLETE documented "
        "workflow as the exact CLI commands it runs, in order — every phase from the "
        "hawkop preflight/auth check and org resolution through the final query. "
        "Pull the real commands straight from the skill (with their flags); do not "
        "summarize them and do not invent them. If hawkop and credentials are "
        "available, you may also run the read-only queries.)"
    ),
    # data-seed: its product is the emitted artifacts, so the walkthrough must name
    # the discovery steps, the minimal seed set, and the files it writes.
    "stackhawk-data-seed": _OBSERVE_HEADER + (
        "2. If (and only if) the data-seed skill applies, write out its COMPLETE "
        "documented workflow in order — the discovery steps, the minimal seed set it "
        "proposes, and the exact artifacts it emits (the data-seed/ directory, "
        "manifest.yaml, and the credentials file). Pull the real steps and commands "
        "straight from the skill; do not summarize them and do not invent them.)"
    ),
}


def observe_suffix(skill: str) -> str:
    """The observe-mode suffix for `skill`, or '' if the skill is unknown."""
    return OBSERVE_SUFFIX.get(skill, "")
