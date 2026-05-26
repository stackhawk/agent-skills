#!/usr/bin/env python3
"""
Cursor Agent eval harness for StackHawk agent skills.

Uses `agent --print --output-format stream-json` (Cursor's headless CLI).
Skills are loaded from cursor/.cursor/rules/*.mdc (alwaysApply rules).

Usage:
    python3 evals/harnesses/cursor/run-evals.py --skill hawkscan
    python3 evals/harnesses/cursor/run-evals.py --skill api
    python3 evals/harnesses/cursor/run-evals.py --skill hawkscan --id hw-07
    python3 evals/harnesses/cursor/run-evals.py --skill hawkscan --dry-run
    python3 evals/harnesses/cursor/run-evals.py --skill hawkscan --full-auto   # actually execute commands

Requirements:
    - Cursor CLI installed and authenticated (`agent status`)
    - Run from the agent-skills repo root
    - cursor/.cursor/rules/ contains generated .mdc files (run generate-cursor-rules.sh)
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HARNESS_DIR = Path(__file__).parent.resolve()
EVALS_DIR   = HARNESS_DIR.parent.parent
REPO_ROOT   = EVALS_DIR.parent
RESULTS_DIR = HARNESS_DIR / "results"
# cursor/.cursor/rules/ contains the alwaysApply .mdc skill rules
CURSOR_RULES_DIR = REPO_ROOT / "cursor" / ".cursor" / "rules"

# ---------------------------------------------------------------------------
# Trigger signals — Cursor-specific tuning.
# Cursor goes directly into execution without the Claude Code "EVALUATE: YES/NO"
# evaluation step, so invocation signals focus on narrative phrases the agent
# uses when kicking off a skill workflow.
# CLI_SIGNALS are checked against shell commands the agent attempted to run.
# ---------------------------------------------------------------------------
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
    # Cursor api: the agent runs hawkop status as its first step, then
    # deeper hawkop commands. Include broader hawkop signals since Cursor
    # doesn't have the false-positive risk of Codex full-auto mode.
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
        "stackhawk-api:api**: yes","stackhawk-api:api** — yes",
        "stackhawk-api:api: yes",  "stackhawk-api:api — yes",
        "stackhawk-api:api - yes",
        "stackhawk-api**: yes",    "stackhawk-api** — yes",
        "stackhawk-api: yes",      "stackhawk-api — yes",
        "stackhawk-api - yes",
        # Cursor narrative-style signals — agent says these instead of evaluating
        "stackhawk api skill",          # "I'll use the StackHawk API skill"
        "stackhawk api",                # "using the StackHawk API"
        "api skill to",                 # "api skill to pull your org..."
        "security posture",             # "pull your org's security posture"
        "untriaged findings",           # "untriaged findings across all apps"
        "scan history",                 # "scan history for"
        "findings across",              # "findings across all apps"
    ],
}

# ---------------------------------------------------------------------------
# Stream-json parsing
# Cursor events: system / user / thinking / assistant / tool_call / result
# ---------------------------------------------------------------------------

def parse_stream(jsonl: str) -> dict:
    bash_commands: list[str] = []
    output_text = ""
    files_written: list[str] = []
    usage: dict = {}
    error = None

    for line in jsonl.splitlines():
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
            if event.get("is_error"):
                error = event.get("result", "unknown error")

    return {
        "bash_commands": bash_commands,
        "files_written": files_written,
        "output_text": output_text.strip(),
        "usage": usage,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Trigger detection — same split-signal approach as Claude Code harness
# ---------------------------------------------------------------------------

def detect_trigger(parsed: dict, skill: str) -> bool:
    cli_haystack = " ".join(parsed["bash_commands"]).lower()
    if any(s.lower() in cli_haystack for s in CLI_SIGNALS.get(skill, [])):
        return True
    text_haystack = parsed["output_text"].lower()
    return any(s.lower() in text_haystack for s in INVOCATION_SIGNALS.get(skill, []))


# ---------------------------------------------------------------------------
# Process checks — shared with Claude Code harness
# ---------------------------------------------------------------------------

def run_process_checks(parsed: dict, checks: list) -> list[dict]:
    haystack = " ".join([
        *parsed["bash_commands"],
        parsed["output_text"],
    ]).lower()
    all_files = " ".join(parsed["files_written"]).lower()

    results = []
    for check in checks:
        ctype = check.get("type", "command_executed")
        signals = [s.lower() for s in check.get("signals", [])]
        antis   = [a.lower() for a in check.get("anti_patterns", [])]

        signal_hit = next((s for s in signals if s in haystack), None)
        anti_hit   = next((a for a in antis   if a in haystack), None)

        if ctype in ("command_negative", "file_content_negative", "output_negative"):
            passed = anti_hit is None
        elif ctype == "file_absent":
            target = check.get("target_file", "").lower()
            passed = target not in all_files
        elif ctype == "conditional_command":
            import re as _re
            m = _re.search(r"'([^']+)'", check.get("condition", ""))
            condition_keyword = m.group(1).lower() if m else None
            if condition_keyword and condition_keyword not in haystack:
                passed = True
            else:
                passed = signal_hit is not None
        elif ctype == "command_preference":
            preferred = [p.lower() for p in check.get("preferred", [])]
            passed = any(p in haystack for p in preferred) and anti_hit is None
        else:
            passed = signal_hit is not None
            if antis:
                passed = passed and anti_hit is None

        results.append({
            "id":           check["id"],
            "pass":         passed,
            "severity":     check.get("severity", "warning"),
            "signal_found": signal_hit,
            "anti_found":   anti_hit,
        })
    return results


def score_checks(results: list[dict]) -> dict:
    blocking_failed = sum(1 for r in results if not r["pass"] and r["severity"] == "blocking")
    warning_failed  = sum(1 for r in results if not r["pass"] and r["severity"] == "warning")
    return {
        "total":           len(results),
        "passed":          sum(1 for r in results if r["pass"]),
        "blocking_failed": blocking_failed,
        "warning_failed":  warning_failed,
        "score":           max(0, 100 - blocking_failed * 15 - warning_failed * 5),
    }


# ---------------------------------------------------------------------------
# Run agent
# ---------------------------------------------------------------------------

def _setup_workspace(skill: str, target_dir: Path) -> None:
    """Copy cursor/.cursor/rules/ into a fresh workspace so alwaysApply rules load."""
    dst = target_dir / ".cursor" / "rules"
    dst.mkdir(parents=True, exist_ok=True)
    for mdc in CURSOR_RULES_DIR.glob("*.mdc"):
        shutil.copy2(mdc, dst / mdc.name)


def run_cursor(
    prompt: str,
    skill: str,
    run_id: str,
    full_auto: bool = False,
    model: str | None = None,
) -> tuple[dict, int]:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_"))
    try:
        _setup_workspace(skill, tmpdir)

        cmd = [
            "agent", "-p", prompt,
            "--output-format", "stream-json",
            "--print",
            "--trust",
        ]
        if model:
            cmd += ["--model", model]
        if full_auto:
            cmd.append("--force")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(tmpdir),
        )

        trace_dir = RESULTS_DIR / skill
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"{run_id}.jsonl").write_text(proc.stdout)

        return parse_stream(proc.stdout), proc.returncode

    except subprocess.TimeoutExpired:
        return {"bash_commands": [], "files_written": [], "output_text": "",
                "usage": {}, "error": "timeout"}, 1
    except FileNotFoundError:
        print("ERROR: 'agent' CLI not found. Install Cursor and ensure it is in PATH.",
              file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cursor Agent eval harness for StackHawk agent skills",
    )
    parser.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id", dest="prompt_id", metavar="RUN_ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-auto", action="store_true",
                        help="Pass --force so the agent can execute commands")
    parser.add_argument("--model", metavar="MODEL_ID",
                        help="Model override (e.g. gpt-5.5, sonnet-4)")
    args = parser.parse_args()

    skill = args.skill
    prompts_path = EVALS_DIR / skill / "prompts.csv"
    checks_path  = EVALS_DIR / skill / "process-checks.json"

    with open(prompts_path) as f:
        all_prompts = list(csv.DictReader(f))
    checks = json.loads(checks_path.read_text())["checks"]

    if args.prompt_id:
        prompts = [p for p in all_prompts if p["id"] == args.prompt_id]
        if not prompts:
            print(f"ERROR: No prompt with id '{args.prompt_id}'", file=sys.stderr)
            sys.exit(1)
    else:
        prompts = all_prompts

    if not CURSOR_RULES_DIR.exists():
        print(f"ERROR: {CURSOR_RULES_DIR} not found. Run scripts/generate-cursor-rules.sh first.",
              file=sys.stderr)
        sys.exit(1)

    mode = "full-auto" if args.full_auto else "observe"
    model_label = f"  |  Model: {args.model}" if args.model else ""
    print(f"\nSkill: {skill}  |  Platform: cursor  |  Mode: {mode}{model_label}  |  Prompts: {len(prompts)}")
    if args.dry_run:
        print("[dry-run — no agent calls]")
    print("─" * 68)

    all_results = []
    total_tokens = {"input": 0, "output": 0}

    for row in prompts:
        run_id         = row["id"]
        prompt         = row["prompt"]
        should_trigger = row["should_trigger"].lower() == "true"
        itype          = row.get("invocation_type", "")

        print(f"\n[{run_id}] {itype:<12}  trigger={'Y' if should_trigger else 'N'}")
        print(f"  {prompt[:92]}{'…' if len(prompt) > 92 else ''}")

        if args.dry_run:
            print("  → skipped")
            continue

        parsed, _exit = run_cursor(prompt, skill, run_id, full_auto=args.full_auto, model=args.model)
        u = parsed.get("usage", {})
        total_tokens["input"]  += u.get("inputTokens", 0)
        total_tokens["output"] += u.get("outputTokens", 0)

        if parsed.get("error"):
            print(f"  ERROR: {parsed['error']}")

        did_trigger = detect_trigger(parsed, skill)
        trigger_ok  = did_trigger == should_trigger

        process_results: list[dict] = []
        scoring = {"total": 0, "passed": 0, "blocking_failed": 0, "warning_failed": 0, "score": 0}
        if should_trigger and did_trigger:
            process_results = run_process_checks(parsed, checks)
            scoring = score_checks(process_results)

        result = {
            "platform":        "cursor",
            "skill":           skill,
            "run_id":          run_id,
            "prompt":          prompt,
            "should_trigger":  should_trigger,
            "did_trigger":     did_trigger,
            "trigger_correct": trigger_ok,
            "bash_commands":   parsed["bash_commands"],
            "files_written":   parsed["files_written"],
            "process_checks":  process_results,
            "scoring":         scoring,
            "usage":           u,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }
        all_results.append(result)

        out_dir = RESULTS_DIR / skill
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{run_id}.result.json").write_text(json.dumps(result, indent=2))

        t_icon    = "✓" if trigger_ok else "✗"
        score_str = f"score={scoring['score']}/100" if process_results else "—"
        print(f"  {t_icon} did_trigger={did_trigger}  {score_str}")
        for pr in process_results:
            if not pr["pass"] and pr["severity"] == "blocking":
                print(f"    BLOCKING FAIL: {pr['id']}")

    if args.dry_run or not all_results:
        return

    trigger_correct = sum(1 for r in all_results if r["trigger_correct"])
    total = len(all_results)
    false_pos = [r for r in all_results if not r["should_trigger"] and r["did_trigger"]]
    false_neg = [r for r in all_results if r["should_trigger"] and not r["did_trigger"]]
    proc_runs = [r for r in all_results if r["process_checks"]]
    avg_score = (sum(r["scoring"]["score"] for r in proc_runs) // len(proc_runs)
                 if proc_runs else None)
    total_blocking = sum(r["scoring"]["blocking_failed"] for r in proc_runs) if proc_runs else 0

    print("\n" + "═" * 68)
    print(f"SUMMARY  skill={skill}  platform=cursor")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Total tokens     : {total_tokens['input']} in / {total_tokens['output']} out")
    print(f"  Results in       : {RESULTS_DIR / skill}/")

    summary = {
        "skill": skill, "platform": "cursor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger_accuracy": {"correct": trigger_correct, "total": total},
        "false_positives":  [r["run_id"] for r in false_pos],
        "false_negatives":  [r["run_id"] for r in false_neg],
        "process_avg_score": avg_score,
        "total_blocking_failures": total_blocking,
        "total_tokens": total_tokens,
        "runs": [{"run_id": r["run_id"], "trigger_correct": r["trigger_correct"],
                  "score": r["scoring"]["score"]} for r in all_results],
    }
    (RESULTS_DIR / skill / "summary.json").write_text(json.dumps(summary, indent=2))

    if false_pos or false_neg or total_blocking > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
