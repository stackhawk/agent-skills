"""agy Harness adapter. Plain-text output (no structured stream).

Pre-shim (5472ed2~1:evals/harnesses/agy/run-evals.py) notes:
- agy outputs plain text — no --output-format flag available.
- Trigger detection scans output_text only; no bash_commands ever populated.
- Skills installed globally via `agy plugin install` (done in CI); load_skill
  toggling is a no-op here.
- AGY_API_KEY passed via os.environ (CI sets it); no special env handling needed.
- Launch: agy -p <prompt> --print-timeout <timeout> [--model M]
- The pre-shim used a unified ALL_SIGNALS dict (no CLI/INVOCATION split) with
  SKILL: prefix signals.  Those are carried in INVOCATION_SIGNALS below alongside
  the backtick-evaluation-format signals shared by codex/cursor adapters.
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile

from evals.lib.models import ParsedRun
from evals.lib.triggers import explicit_decision, decide_trigger
from evals.lib.observe import observe_suffix

# CLI_SIGNALS: agy emits plain text — there are no shell commands to scan.
CLI_SIGNALS: dict[str, list[str]] = {
    "hawkscan": [],
    "api": [],
    "stackhawk-data-seed": [],
    # agy is text-only: CLI_SIGNALS here are matched against prose output, where a
    # hit would override a declared `none: NO` (executed_cli wins in decide_trigger).
    # So, like the other three skills above, hawkscan-ci's agy CLI_SIGNALS stay empty —
    # all detection goes through INVOCATION_SIGNALS, where a declared NO can still win.
    "hawkscan-ci": [],
}

# INVOCATION_SIGNALS: checked against output_text.
# Combines the pre-shim ALL_SIGNALS (SKILL: prefix variants) with the
# evaluation-format backtick signals used by the shared skill prompts.
INVOCATION_SIGNALS: dict[str, list[str]] = {
    "hawkscan": [
        # Pre-shim ALL_SIGNALS (verbatim from 5472ed2~1:evals/harnesses/agy/run-evals.py)
        "skill: hawkscan",
        "skill:hawkscan",
        # Evaluation-format variants emitted by the shared skill evaluation suffix
        "hawkscan:hawkscan`: yes",
        "hawkscan:hawkscan` — yes",
        "hawkscan:hawkscan**: yes",
        "hawkscan:hawkscan** — yes",
        "hawkscan:hawkscan: yes",
        "hawkscan:hawkscan — yes",
        # Action-intent phrases
        "autonomous security scan",
        "dast scan after code",
        "dast scan triggered",
        "dast scan required",
        "security scan required",
        "security scan after",
        "run the security scan",
        "running the hawkscan",
        "running the security scan",
    ],
    "api": [
        # Pre-shim ALL_SIGNALS (verbatim)
        "skill: api",
        "skill:api",
        "skill: stackhawk-api",
        # Evaluation-format variants
        "stackhawk-api:api`: yes",
        "stackhawk-api:api` — yes",
        "stackhawk-api:api: yes",
        "stackhawk-api:api — yes",
    ],
    "stackhawk-data-seed": [
        "skill: stackhawk-data-seed",
        "skill:stackhawk-data-seed",
        "stackhawk-data-seed:stackhawk-data-seed`: yes",
        "stackhawk-data-seed:stackhawk-data-seed: yes",
        "stackhawk-data-seed:stackhawk-data-seed — yes",
        "stackhawk-data-seed: yes", "stackhawk-data-seed — yes",
        "seed data for hawkscan", "seed this repo", "minimum seed entities",
        "data seed complete", "data-seed/manifest",
    ],
    "hawkscan-ci": [
        "hawkscan-ci:hawkscan-ci`: yes", "hawkscan-ci:hawkscan-ci` — yes",
        "hawkscan-ci:hawkscan-ci**: yes", "hawkscan-ci:hawkscan-ci** — yes",
        "hawkscan-ci:hawkscan-ci: yes", "hawkscan-ci:hawkscan-ci — yes",
        "hawkscan-ci:hawkscan-ci - yes", "hawkscan-ci**: yes",
        "hawkscan-ci** — yes", "hawkscan-ci** - yes", "hawkscan-ci: yes",
        "hawkscan-ci — yes", "hawkscan-ci - yes",
        "set up hawkscan in ci", "wire hawkscan into", "stackhawk/hawkscan-action",
        "add stackhawk to my pipeline", "hawkscan in your pipeline",
    ],
}

# Matches pre-shim default --print-timeout (180s); bumped slightly for safety.
PRINT_TIMEOUT = "240s"

# Appended to every prompt before invoking agy (verbatim from pre-shim
# 5472ed2~1:evals/harnesses/agy/run-evals.py). In --print mode agy hangs on tool
# approvals, so this asks the agent to declare its skill choice up front — that
# declaration is what explicit_decision + INVOCATION_SIGNALS detect. Without it,
# live agy runs produce no detectable trigger text (all false-negatives). agy now
# uses the shared per-skill observe suffix (evals/lib/observe.py), aligning its
# declaration format and workflow-enumeration ask with the other harnesses.


def parse_stream(raw: str) -> ParsedRun:
    """agy outputs plain text — wrap entirely in output_text; no commands to parse."""
    return ParsedRun(output_text=raw.strip())


class AgyAdapter:
    platform = "agy"
    # Skills are installed globally via `agy plugin install`, so toggling
    # load_skill has no effect — the with/without compare runs are identical and
    # lift is not measurable for this platform. compare_skill annotates rows with
    # a note when this is set so the lift output isn't read as "skill had no effect."
    load_skill_is_noop = True

    def cli_signals(self, skill: str) -> list[str]:
        return CLI_SIGNALS.get(skill, [])

    def invocation_signals(self, skill: str) -> list[str]:
        return INVOCATION_SIGNALS.get(skill, [])

    def parse_stream(self, raw: str) -> ParsedRun:
        return parse_stream(raw)

    def detect_trigger(self, run: ParsedRun, skill: str) -> bool:
        # agy is text-only; CLI signals may appear in prose too, so check both
        # lists against the combined text. An explicit decline still overrides a
        # loose phrase match (e.g. the agent quoting a "don't scan" instruction).
        hay = (" ".join(run.bash_commands) + " " + run.output_text).lower()
        cli_hit = any(s.lower() in hay for s in self.cli_signals(skill))
        loose = any(s.lower() in hay for s in self.invocation_signals(skill))
        return decide_trigger(executed_cli=cli_hit,
                              declared=explicit_decision(run.output_text, skill),
                              loose_hit=loose)

    def launch(
        self,
        prompt: str,
        skill: str,
        run_id: str,
        plugin_dirs: list[str],
        *,
        model: str | None,
        load_skill: bool,
        max_budget: float,
        bare: bool,
        full_auto: bool,
    ) -> ParsedRun:
        # Skills are installed globally via `agy plugin install` in CI;
        # load_skill toggling is a no-op here.
        tmpdir = tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_")
        try:
            # --print mode hangs on tool approvals; the suffix makes agy declare
            # its skill choice up front so detect_trigger has text to match. agy is
            # text-only (no real execution), so observe mode is its only mode.
            effective_prompt = prompt + observe_suffix(skill)
            cmd = ["agy", "-p", effective_prompt, "--print-timeout", PRINT_TIMEOUT]
            if model:
                cmd += ["--model", model]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=420,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                return ParsedRun(error="timeout")
            run = parse_stream(proc.stdout)
            run.returncode = proc.returncode
            run.stderr_tail = (proc.stderr or "")[-2000:]
            # agy has no non-interactive auth (relies on OAuth; see upstream
            # google-antigravity/antigravity-cli#78). In a browser-less CI runner
            # it prints an auth URL and times out. Label that distinctly so the
            # digest doesn't read it as an eval/plumbing failure on our side.
            blob = (run.output_text + " " + run.stderr_tail).lower()
            if "authentication required" in blob or "authentication timed out" in blob:
                run.error = "agy: no headless auth (upstream antigravity-cli#78) — not runnable in CI"
            elif proc.returncode != 0 and not run.error:
                run.error = f"exit {proc.returncode}: {run.stderr_tail[-300:].strip()}"
            elif not run.output_text and not run.bash_commands and not run.error:
                run.error = f"empty output (exit {proc.returncode})"
            return run
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


ADAPTER = AgyAdapter()
