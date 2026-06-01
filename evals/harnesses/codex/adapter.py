"""codex Harness adapter. Parsing + signals ported from pre-shim run-evals.py."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile

from evals.lib.models import ParsedRun

# CLI signals — checked against bash_commands only (prevents documentation content
# from creating false positives when the agent writes README/guides about HawkScan).
CLI_SIGNALS = {
    "hawkscan": [
        "hawk scan",
        "hawk validate",
        "hawk rescan",
        # "hawk version" excluded: running 'hawk version' alone is common for
        # installation-check tasks and would cause false positives. The preflight
        # workflow always also runs 'hawk config --help', so 'hawk config' below suffices.
        "hawk config",
        "hawk create app",
        "hawk init",
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
        if any(s.lower() in cli for s in self.cli_signals(skill)):
            return True
        text = run.output_text.lower()
        return any(s.lower() in text for s in self.invocation_signals(skill))

    def launch(self, prompt, skill, run_id, plugin_dirs, *, model, load_skill,
               max_budget, bare, full_auto) -> ParsedRun:
        tmpdir = tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_")
        try:
            cmd = [
                "codex", "exec", "--json",
                "--sandbox", "workspace-write",
                "--skip-git-repo-check",
            ]
            if model:
                cmd += ["-m", model]
            if not full_auto:
                cmd += ["--sandbox", "read-only"]
            cmd.append(prompt)
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
