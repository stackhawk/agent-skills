"""cursor Harness adapter. Parsing + signals ported from pre-shim run-evals.py."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from evals.lib.models import ParsedRun

# adapter.py -> cursor -> harnesses -> evals -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# cursor/.cursor/rules/ holds the alwaysApply .mdc skill rules (pre-shim path).
CURSOR_RULES_DIR = REPO_ROOT / "cursor" / ".cursor" / "rules"


def _setup_skill(target_dir: str) -> None:
    """Copy cursor/.cursor/rules/*.mdc into the run's workspace so alwaysApply
    rules load. Mirrors the pre-shim run-evals.py _setup_workspace()."""
    dst = Path(target_dir) / ".cursor" / "rules"
    dst.mkdir(parents=True, exist_ok=True)
    for mdc in CURSOR_RULES_DIR.glob("*.mdc"):
        shutil.copy2(mdc, dst / mdc.name)

# CLI signals — checked against bash_commands only.
# Cursor goes directly into execution, so CLI signals are the primary trigger
# indicator. Invocation signals cover narrative phrases the agent uses when
# kicking off a skill workflow without immediately running commands.
CLI_SIGNALS = {
    "hawkscan": [
        "hawk scan",
        "hawk validate",
        "hawk rescan",
        "hawk config",
        "hawk create app",
        "hawk init",
        "hawk perch",
    ],
    # Cursor api: agent runs hawkop status as its first step, then deeper
    # hawkop commands. Broader hawkop signals included since Cursor doesn't
    # have false-positive risk of Codex full-auto mode.
    "api": [
        "hawkop status",
        "hawkop scan get",
        "hawkop org get",
        "hawkop org set",
        "hawkop app list",
        "/api/v2/org",
        "/api/v1/scan",
        "hawk_api GET",
    ],
}

# Invocation signals — checked against output_text only.
# Cursor doesn't use the Claude Code "EVALUATE: YES/NO" evaluation step, so
# these focus on narrative phrases the agent uses when kicking off a skill workflow.
INVOCATION_SIGNALS = {
    "hawkscan": [
        "hawkscan:hawkscan`: yes", "hawkscan:hawkscan` — yes",
        "hawkscan:hawkscan**: yes", "hawkscan:hawkscan** — yes",
        "hawkscan:hawkscan: yes",  "hawkscan:hawkscan — yes",
        "hawkscan:hawkscan - yes", "hawkscan:hawkscan - **yes",
        "hawkscan** - yes", "hawkscan** — yes",
        "hawkscan**: yes",  "hawkscan: yes",
        "hawkscan — yes",   "hawkscan - yes",
        "autonomous security scan",
        "dast scan after code", "dast scan triggered", "dast scan required",
        "security scan required", "security scan after",
        "run the security scan",  "running the hawkscan",
    ],
    "api": [
        # Claude Code evaluation-format signals (if model uses that format)
        "stackhawk-api:api`: yes", "stackhawk-api:api` — yes",
        "stackhawk-api:api**: yes", "stackhawk-api:api** — yes",
        "stackhawk-api:api: yes",  "stackhawk-api:api — yes",
        "stackhawk-api:api - yes",
        "stackhawk-api**: yes",    "stackhawk-api** — yes",
        "stackhawk-api: yes",      "stackhawk-api — yes",
        "stackhawk-api - yes",
        # Cursor narrative-style signals
        "stackhawk api skill",
        "stackhawk api",
        "api skill to",
        "security posture",
        "untriaged findings",
        "scan history",
        "findings across",
    ],
}


def parse_stream(raw: str) -> ParsedRun:
    """Parse cursor stream-json output.

    Cursor event shapes (from pre-shim run-evals.py):
      - type="assistant":  message.content[] with blocks of type="text"
      - type="tool_call" subtype="started":
            tool_call.shellToolCall.args.command  -> bash_commands
            tool_call.writeToolCall.args.path     -> files_written
      - type="result":  usage.outputTokens, is_error, result
    """
    bash_commands: list[str] = []
    files_written: list[str] = []
    output_text = ""
    output_tokens: int | None = None
    error = None

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
                if block.get("type") == "text":
                    output_text += block.get("text", "") + "\n"

        elif etype == "tool_call" and event.get("subtype") == "started":
            tc = event.get("tool_call", {})
            # Shell command
            shell = tc.get("shellToolCall", {})
            if shell:
                cmd = shell.get("args", {}).get("command", "")
                if cmd:
                    bash_commands.append(cmd)
            # File write
            write = tc.get("writeToolCall", {})
            if write:
                path = write.get("args", {}).get("path", "")
                if path:
                    files_written.append(path)

        elif etype == "result":
            usage = event.get("usage", {})
            otok = usage.get("outputTokens")
            if otok is not None:
                output_tokens = (output_tokens or 0) + int(otok)
            if event.get("is_error"):
                error = event.get("result", "unknown error")

    return ParsedRun(
        bash_commands=bash_commands,
        files_written=files_written,
        output_text=output_text.strip(),
        output_tokens=output_tokens or None,
        error=error,
    )


class CursorAdapter:
    platform = "cursor"

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
            # With/without-skill switch: only install the cursor rules when the
            # skill should be loaded (pre-shim always installed them).
            if load_skill:
                _setup_skill(tmpdir)
            api_key = os.environ.get("CURSOR_API_KEY", "")
            cmd = [
                "agent", "-p", prompt,
                "--output-format", "stream-json",
                "--print",
                "--trust",
            ]
            if api_key:
                cmd += ["--api-key", api_key]
            if model:
                cmd += ["--model", model]
            if full_auto:
                cmd.append("--force")
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                return ParsedRun(error="timeout")
            return parse_stream(proc.stdout)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


ADAPTER = CursorAdapter()
