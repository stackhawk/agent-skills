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
  - api is a read-workflow over hawk op; it degrades gracefully (narrate if creds
    absent, run the read-only queries if present).
  - data-seed's product is the artifacts it emits (manifest + data-seed/), so its
    walkthrough must enumerate those.

Every harness shares this config and the same `plugin:skill: YES`/`none: NO`
decision format, so trigger detection is uniform across harnesses. Appended only
in observe mode — full-auto / extended runs against a real target use the bare
prompt.
"""
from __future__ import annotations

# Anti-refusal core (all skills): in headless `-p` mode a model may have only the
# skill's description, not its body. A rigid "do not invent" then makes weak models
# refuse — "I can't access the skill definition, should I read it?" (haiku scored 0
# this way). So tell it to invoke/load the skill and not pause to ask permission.
_USE_SKILL = (
    "Use the skill's own steps — if its full definition isn't already in your "
    "context, invoke/load the skill to get them; do NOT pause to ask permission to "
    "read or load it."
)

# Command-emission guidance is PER-SKILL. "Include the command even if unsure of a
# flag" is safe for hawkscan/api (listing commands has no side effect) but wrong for
# data-seed: it's a code-EMITTER, and narrating a startup command like
# `docker-compose up` trips its no-startup anti-pattern. data-seed therefore gets
# read-only discovery guidance instead.
_CMDS_OK = (
    " Give the real commands with their flags, not a prose summary; if you can't "
    "recall an exact flag, include the command anyway rather than skipping the step."
)
_DATA_SEED_GUIDANCE = (
    " Give the real discovery commands and the artifacts emitted, not a prose "
    "summary. Discovery only READS the repo; data-seed emits files and never starts "
    "services — do NOT run or list app-startup commands (docker compose up, npm "
    "start, ./gradlew bootRun, etc.)."
)

_OBSERVE_HEADER = (
    "\n\n---\n"
    "(Eval harness — observe mode. The target app, credentials, or prior scans may "
    "be unavailable here. Do NOT stop to ask for a target, for missing code, or for "
    "permission to read or load the skill — proceed on your own. Output exactly:\n"
    "1. A decision line naming the StackHawk skill this request should invoke, "
    "written exactly as `hawkscan:hawkscan: YES`, `stackhawk-api:api: YES`, "
    "`stackhawk-data-seed:stackhawk-data-seed: YES`, "
    "`hawkscan-ci:hawkscan-ci: YES`, `stackhawk-optimize:optimize: YES`, "
    "or `none: NO`.\n"
)

OBSERVE_SUFFIX = {
    # hawkscan: no live target here, so executing the scan stalls — keep it a
    # pure paper walkthrough of the full command sequence.
    "hawkscan": _OBSERVE_HEADER + (
        "2. If (and only if) the hawkscan skill applies, write out its COMPLETE "
        "documented workflow as the exact CLI commands it runs, in order — every "
        "phase from preflight through the verifying rescan. This is a paper "
        "walkthrough: do NOT try to run the scan, there is no live target here. "
        + _USE_SKILL + _CMDS_OK + ")"
    ),
    # api: a read-workflow over hawk op. Narrate the full command sequence; if
    # the hawk CLI + credentials happen to be present, the read-only queries may also run.
    "api": _OBSERVE_HEADER + (
        "2. If (and only if) the api skill applies, write out its COMPLETE documented "
        "workflow as the exact CLI commands it runs, in order — every phase from the "
        "hawk op preflight/auth check and org resolution through the final query. "
        + _USE_SKILL + _CMDS_OK + " If the hawk CLI and credentials are available, you may "
        "also run the read-only queries.)"
    ),
    # data-seed: its product is the emitted artifacts, so the walkthrough must name
    # the discovery steps, the minimal seed set, and the files it writes.
    "stackhawk-data-seed": _OBSERVE_HEADER + (
        "2. If (and only if) the data-seed skill applies, write out its COMPLETE "
        "documented workflow in order — the discovery steps, the minimal seed set it "
        "proposes, and the exact artifacts it emits (the data-seed/ directory, "
        "manifest.yaml, and the credentials file). " + _USE_SKILL + _DATA_SEED_GUIDANCE + ")"
    ),
    # hawkscan-ci: no live scan and no real repo here — its product is the CI
    # pipeline BLOCK it would write plus the secret/out-of-band instructions. It must
    # NOT run git, push, open a PR, set the secret, or trigger the pipeline; if
    # stackhawk.yml is missing it hands off to the hawkscan skill instead.
    "hawkscan-ci": _OBSERVE_HEADER + (
        "2. If (and only if) the hawkscan-ci skill applies, produce the exact CI "
        "pipeline block you would write for the detected provider — the secret "
        "reference, app startup, COMMIT_SHA/BRANCH_NAME export, the HawkScan "
        "invocation, exit-code handling, and artifact upload — then list the "
        "out-of-band steps the user must do themselves (set the secret, branch "
        "protection). Do NOT run git, push a branch, open a PR, set the secret "
        "yourself, or trigger the pipeline. If stackhawk.yml is missing or invalid, "
        "say so and hand off to the hawkscan skill instead of writing a workflow. "
        + _USE_SKILL + _CMDS_OK + ")"
    ),
    # optimize: builds a non-destructive trial scan policy (Setup) and tunes from
    # per-path metrics (Refine). No live target here, so keep it a paper walkthrough
    # of the full Setup→Refine command sequence; do NOT run a trial scan.
    "optimize": _OBSERVE_HEADER + (
        "2. If (and only if) the optimize skill applies, write out its COMPLETE "
        "documented workflow as the exact CLI commands it runs, in order — Setup "
        "(preflight `hawk op policy create --help` and `hawk op scan metrics --help`, "
        "map tech flags, build the named trial policy with `hawk op policy create`, "
        "back up + edit stackhawk.yml to reference `app.scanPolicy.name`) then Refine "
        "(trial scan, `hawk op scan metrics <SCAN_ID> --format json`, tune "
        "concurrentRequests/excludePaths, then promote or discard). This is a paper "
        "walkthrough: do NOT run the trial scan, there is no live target here. "
        + _USE_SKILL + _CMDS_OK + ")"
    ),
}


def observe_suffix(skill: str) -> str:
    """The observe-mode suffix for `skill`, or '' if the skill is unknown."""
    return OBSERVE_SUFFIX.get(skill, "")
