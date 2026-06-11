"""codex Harness adapter. Parsing + signals ported from pre-shim run-evals.py."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile

from evals.lib.models import ParsedRun
from evals.lib.triggers import explicit_decision, decide_trigger
from evals.lib.observe import observe_suffix

# CLI signals — checked against bash_commands only (prevents documentation content
# from creating false positives when the agent writes README/guides about HawkScan).
CLI_SIGNALS = {
    # Scan-distinctive commands only — generic preflight (hawk version/config/init)
    # over-triggers when the agent merely assesses the environment for a non-scan
    # request. Triggering falls back to the explicit decision line otherwise.
    "hawkscan": [
        "hawk scan",
        "hawk validate",
        "hawk rescan",
        "hawk create app",
        "hawk perch",
    ],
    # Signals specific to the api reporting workflow — avoids false positives
    # from hawkop status/app/env commands that the hawkscan skill also runs.
    "api": [
        "hawkop scan get",     # api Step 4: app deep dive
        "hawkop org get",      # api Step 1: establish orgId
        "hawkop org set",      # api Step 1: switch org
        "/api/v2/org",         # api Step 3: org posture endpoint (hawkop doesn't wrap it)
        "/api/v1/scan",        # api Step 4: raw scan drill-down
        "hawk_api GET",        # api raw API helper function
    ],
    # data-seed emits checked-in artifacts rather than a distinctive CLI.
    "stackhawk-data-seed": ["data-seed/", "data-seed/manifest", ".data-seed-credentials",
                            "manifest.yaml"],
    # hawkscan-ci has no distinctive CLI; the closest "it ran" signal is the agent
    # executing provider-detection globs over CI config files. The workflow artifacts
    # it WRITES (stackhawk/hawkscan-action, the docker image) are narrated output, so
    # they live in INVOCATION_SIGNALS, not here.
    "hawkscan-ci": [".github/workflows", ".gitlab-ci.yml", "Jenkinsfile",
                    ".circleci/config.yml"],
}

# Invocation signals — checked against output_text only. In full-auto mode these are
# belt-and-suspenders: the agent usually runs CLI commands directly. They catch
# contextual prompts where the skill fires but the agent finds an empty working dir
# and stops before reaching the CLI (same as observe mode in Claude Code harness).
INVOCATION_SIGNALS = {
    "hawkscan": [
        # All markdown formatting variants the model uses around `: YES` or ` — YES`
        "hawkscan:hawkscan`: yes",   # backtick + colon
        "hawkscan:hawkscan` — yes",  # backtick + dash
        "hawkscan:hawkscan**: yes",  # bold + colon
        "hawkscan:hawkscan** — yes", # bold + dash
        "hawkscan:hawkscan: yes",    # plain colon
        "hawkscan:hawkscan — yes",   # plain dash
        # Specific action-intent phrases
        "autonomous security scan",
        "dast scan after code",
        "dast scan triggered",
        "dast scan required",
        "security scan required",
        "security scan after",
        "run the security scan",
        "running the hawkscan",
    ],
    "api": [
        "stackhawk-api:api`: yes",
        "stackhawk-api:api` — yes",
        "stackhawk-api:api: yes",
        "stackhawk-api:api — yes",
    ],
    "stackhawk-data-seed": [
        "stackhawk-data-seed:stackhawk-data-seed`: yes",
        "stackhawk-data-seed:stackhawk-data-seed` — yes",
        "stackhawk-data-seed:stackhawk-data-seed**: yes",
        "stackhawk-data-seed:stackhawk-data-seed** — yes",
        "stackhawk-data-seed:stackhawk-data-seed: yes",
        "stackhawk-data-seed:stackhawk-data-seed — yes",
        "stackhawk-data-seed: yes", "stackhawk-data-seed — yes",
        "seed data for hawkscan", "seed this repo", "minimum seed entities",
        "seed entities required", "data seed complete", "data-seed/manifest",
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


def parse_stream(raw: str) -> ParsedRun:
    cmds, out, otok, err, seen = [], "", 0, None, set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type", "")
        if t == "item.started":
            it = ev.get("item", {})
            if it.get("type") == "command_execution":
                c = it.get("command", "")
                if c and c not in seen:
                    cmds.append(c)
                    seen.add(c)
        elif t == "item.completed":
            it = ev.get("item", {})
            if it.get("type") in ("message", "agent_message"):
                txt = it.get("text", "")
                if txt:
                    out += txt + "\n"
                content = it.get("content", "")
                if isinstance(content, str):
                    out += content + "\n"
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            out += b.get("text", "") + "\n"
        elif t == "turn.completed":
            otok += ev.get("usage", {}).get("output_tokens", 0)
        elif t == "error":
            err = ev.get("message", "unknown error")
    return ParsedRun(bash_commands=cmds, output_text=out.strip(),
                     output_tokens=otok or None, error=err)


class CodexAdapter:
    platform = "codex"

    def cli_signals(self, skill): return CLI_SIGNALS.get(skill, [])
    def invocation_signals(self, skill): return INVOCATION_SIGNALS.get(skill, [])
    def parse_stream(self, raw): return parse_stream(raw)

    def detect_trigger(self, run: ParsedRun, skill: str) -> bool:
        cli = " ".join(run.bash_commands).lower()
        executed = any(s.lower() in cli for s in self.cli_signals(skill))
        text = run.output_text.lower()
        loose = any(s.lower() in text for s in self.invocation_signals(skill))
        return decide_trigger(executed_cli=executed,
                              declared=explicit_decision(run.output_text, skill),
                              loose_hit=loose)

    def launch(self, prompt, skill, run_id, plugin_dirs, *, model, load_skill,
               max_budget, bare, full_auto) -> ParsedRun:
        tmpdir = tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_")
        try:
            # In CI the bubblewrap sandbox can't initialize (Ubuntu 24.04 blocks
            # unprivileged user namespaces), so codex exits at sandbox startup
            # before running any command — the agent can't reach hawk. Bypass the
            # sandbox there; it's safe on an ephemeral runner in a throwaway tmpdir,
            # and the agent needs write+exec to run the skill workflow anyway.
            # Locally, keep the real sandbox (workspace-write for full-auto,
            # else read-only). Passing --sandbox twice makes codex exit 2.
            if os.environ.get("CI"):
                cmd = [
                    "codex", "exec", "--json",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                ]
            else:
                sandbox = "workspace-write" if full_auto else "read-only"
                cmd = [
                    "codex", "exec", "--json",
                    "--sandbox", sandbox,
                    "--skip-git-repo-check",
                ]
            if model:
                cmd += ["-m", model]
            # Observe mode: append the per-skill walkthrough suffix. Full-auto /
            # extended runs against a real target use the bare prompt.
            cmd.append(prompt if full_auto else prompt + observe_suffix(skill))
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=300, cwd=tmpdir)
            except subprocess.TimeoutExpired:
                return ParsedRun(error="timeout")
            run = parse_stream(proc.stdout)
            run.returncode = proc.returncode
            run.stderr_tail = (proc.stderr or "")[-2000:]
            if proc.returncode != 0 and not run.error:
                run.error = f"exit {proc.returncode}: {run.stderr_tail[-300:].strip()}"
            elif not run.output_text and not run.bash_commands and not run.error:
                run.error = f"empty output (exit {proc.returncode})"
            return run
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


ADAPTER = CodexAdapter()
