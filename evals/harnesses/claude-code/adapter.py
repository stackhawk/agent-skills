"""claude-code Harness adapter. Parsing + signal lists ported from run-evals.py."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile

from evals.lib.models import ParsedRun

CLI_SIGNALS = {
    "hawkscan": ["hawk scan", "hawk validate", "hawk rescan", "hawk config",
                 "hawk create app", "hawk init", "hawk perch"],
    "api": ["hawkop scan", "hawkop app", "hawkop org", "hawkop env", "hawkop status",
            "hawkop init", "/api/v1/scan", "/api/v2/org", "hawk_api GET"],
}

INVOCATION_SIGNALS = {
    "hawkscan": [
        "hawkscan:hawkscan`: yes", "hawkscan:hawkscan` — yes", "hawkscan:hawkscan**: yes",
        "hawkscan:hawkscan** — yes", "hawkscan:hawkscan: yes", "hawkscan:hawkscan — yes",
        "hawkscan:hawkscan - yes", "hawkscan:hawkscan - **yes", "hawkscan**: yes",
        "hawkscan** — yes", "hawkscan** - yes", "hawkscan: yes", "hawkscan — yes",
        "hawkscan - yes", "autonomous security scan", "dast scan after code",
        "dast scan triggered", "dast scan required", "security scan required",
        "security scan after", "run the security scan", "running the hawkscan",
    ],
    "api": [
        "stackhawk-api:api`: yes", "stackhawk-api:api` — yes", "stackhawk-api:api**: yes",
        "stackhawk-api:api** — yes", "stackhawk-api:api: yes", "stackhawk-api:api — yes",
        "stackhawk-api:api - yes", "stackhawk-api**: yes", "stackhawk-api** — yes",
        "stackhawk-api** - yes", "stackhawk-api: yes", "stackhawk-api — yes",
        "stackhawk-api - yes",
    ],
}


def parse_stream(raw: str) -> ParsedRun:
    bash, written, edited, text, cost, err = [], [], [], "", 0.0, None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type", "")
        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                bt = block.get("type", "")
                if bt == "text":
                    text += block.get("text", "") + "\n"
                elif bt == "tool_use":
                    name, inp = block.get("name", ""), block.get("input", {})
                    if name == "Bash" and inp.get("command"):
                        bash.append(inp["command"])
                    elif name == "Write" and inp.get("file_path"):
                        written.append(inp["file_path"])
                    elif name == "Edit" and inp.get("file_path"):
                        edited.append(inp["file_path"])
        elif etype == "result":
            cost = event.get("total_cost_usd") or event.get("cost_usd") or 0.0
            text += event.get("result", "")
            if event.get("subtype") == "error_during_execution":
                err = event.get("result", "unknown error")
    return ParsedRun(bash_commands=bash, files_written=written, files_edited=edited,
                     output_text=text.strip(), cost_usd=cost, error=err)


class ClaudeCodeAdapter:
    platform = "claude-code"

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
            cmd = ["claude", "-p", prompt, "--output-format", "stream-json",
                   "--verbose", "--no-session-persistence",
                   "--max-budget-usd", str(max_budget)]
            if model:
                cmd += ["--model", model]
            if load_skill:
                for pd in plugin_dirs:
                    cmd += ["--plugin-dir", pd]
            if full_auto:
                cmd.append("--dangerously-skip-permissions")
            if bare:
                cmd.append("--bare")
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


ADAPTER = ClaudeCodeAdapter()
