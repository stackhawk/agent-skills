#!/usr/bin/env python3
"""
GitHub Copilot CLI eval harness for StackHawk agent skills.

Uses `copilot -p --output-format json --allow-all-tools --plugin-dir`.
Skills are loaded from plugins/<skill>/ via --plugin-dir.

The trigger detection is uniquely reliable: Copilot emits an explicit
  tool.execution_start {"toolName":"skill","arguments":{"skill":"hawkscan"}}
event when the skill fires. No heuristic text-matching needed.

Usage:
    python3 evals/harnesses/copilot/run-evals.py --skill hawkscan
    python3 evals/harnesses/copilot/run-evals.py --skill api
    python3 evals/harnesses/copilot/run-evals.py --skill hawkscan --id hw-07
    python3 evals/harnesses/copilot/run-evals.py --skill hawkscan --dry-run
    python3 evals/harnesses/copilot/run-evals.py --skill hawkscan --model gpt-5.3-codex

Requirements:
    - GitHub Copilot CLI installed and authenticated (copilot login)
    - Run from the agent-skills repo root

Note: Copilot actually executes commands (--allow-all-tools), so process
check scores reflect real hawk workflow completion — not just observations.
"""

import argparse
import csv
import json
import os
import re
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

# ---------------------------------------------------------------------------
# Trigger detection
# Copilot emits an unambiguous tool.execution_start event when a skill fires:
#   {"type":"tool.execution_start","data":{"toolName":"skill","arguments":{"skill":"hawkscan"}}}
# This eliminates all heuristic signal-matching needed for other platforms.
# ---------------------------------------------------------------------------

def detect_trigger(parsed: dict, skill: str) -> bool:
    # Primary: explicit skill tool call (unambiguous)
    for call in parsed.get("skill_calls", []):
        if call.lower() == skill.lower() or call.lower() == f"stackhawk-{skill}".lower():
            return True

    # Fallback: CLI signals in bash commands (belt-and-suspenders)
    cli_signals = {
        "hawkscan": ["hawk scan", "hawk validate", "hawk rescan", "hawk config",
                     "hawk create app", "hawk init", "hawk perch"],
        "api": ["hawkop scan get", "hawkop org get", "/api/v2/org", "/api/v1/scan"],
    }
    cmd_haystack = " ".join(parsed.get("bash_commands", [])).lower()
    return any(s.lower() in cmd_haystack for s in cli_signals.get(skill, []))


# ---------------------------------------------------------------------------
# Stream-json parsing — Copilot JSONL event format:
#   tool.execution_start  {"toolName":"bash","arguments":{"command":"..."}}
#   tool.execution_start  {"toolName":"skill","arguments":{"skill":"hawkscan"}}
#   tool.execution_partial_result {"partialOutput":"..."}
#   assistant.message     {"content":"..."}
#   result                {}
# ---------------------------------------------------------------------------

def parse_stream(jsonl: str) -> dict:
    bash_commands: list[str] = []
    files_written: list[str] = []
    skill_calls:   list[str] = []
    output_text  = ""
    usage: dict  = {}
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
        data  = event.get("data", {})

        if etype == "tool.execution_start":
            tool_name = data.get("toolName", "")
            args      = data.get("arguments", {})

            if tool_name == "bash":
                cmd = args.get("command", "")
                if cmd:
                    bash_commands.append(cmd)

            elif tool_name == "skill":
                skill_name = args.get("skill", "")
                if skill_name:
                    skill_calls.append(skill_name)

            elif tool_name in ("write_file", "create_file", "str_replace_editor"):
                path = args.get("path") or args.get("file_path") or ""
                if path:
                    files_written.append(path)

        elif etype == "assistant.message":
            content = data.get("content", "")
            if content:
                output_text += content + "\n"

        elif etype == "result":
            usage = data.get("usage", {})
            if data.get("error"):
                error = str(data["error"])

    return {
        "bash_commands": bash_commands,
        "files_written": files_written,
        "skill_calls":   skill_calls,
        "output_text":   output_text.strip(),
        "usage":         usage,
        "error":         error,
    }


# ---------------------------------------------------------------------------
# Process checks
# ---------------------------------------------------------------------------

def run_process_checks(parsed: dict, checks: list) -> list[dict]:
    haystack = " ".join([
        *parsed["bash_commands"],
        parsed["output_text"],
    ]).lower()
    all_files = " ".join(parsed["files_written"]).lower()

    results = []
    for check in checks:
        ctype   = check.get("type", "command_executed")
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
            m = re.search(r"'([^']+)'", check.get("condition", ""))
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
# Run copilot
# ---------------------------------------------------------------------------

def run_copilot(
    prompt: str,
    skill: str,
    run_id: str,
    model: str | None = None,
) -> tuple[dict, int]:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_"))
    try:
        plugin_dir = str(REPO_ROOT / "plugins" / skill)

        cmd = [
            "copilot", "-p", prompt,
            "--output-format", "json",
            "--allow-all-tools",
            "--plugin-dir", plugin_dir,
            "--no-ask-user",
        ]
        if model:
            cmd += ["--model", model]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(tmpdir),
            env={**os.environ},
        )

        trace_dir = RESULTS_DIR / skill
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"{run_id}.jsonl").write_text(proc.stdout)

        parsed = parse_stream(proc.stdout)
        if proc.returncode != 0 and not parsed["output_text"] and not parsed["skill_calls"]:
            stderr = proc.stderr.strip()
            if stderr:
                parsed["error"] = stderr[:300]

        return parsed, proc.returncode

    except subprocess.TimeoutExpired:
        return {"bash_commands": [], "files_written": [], "skill_calls": [],
                "output_text": "", "usage": {}, "error": "timeout"}, 1
    except FileNotFoundError:
        print("ERROR: 'copilot' CLI not found. Install GitHub Copilot CLI.", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GitHub Copilot CLI eval harness for StackHawk agent skills",
    )
    parser.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id", dest="prompt_id", metavar="RUN_ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", metavar="MODEL_ID",
                        help="Model override (e.g. gpt-5.3-codex)")
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

    model_label = f"  |  Model: {args.model}" if args.model else ""
    print(f"\nSkill: {skill}  |  Platform: copilot  |  Mode: full-auto{model_label}  |  Prompts: {len(prompts)}")
    if args.dry_run:
        print("[dry-run — no copilot calls]")
    print("─" * 68)

    all_results = []

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

        parsed, _exit = run_copilot(prompt, skill, run_id, model=args.model)

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
            "platform":        "copilot",
            "skill":           skill,
            "run_id":          run_id,
            "prompt":          prompt,
            "should_trigger":  should_trigger,
            "did_trigger":     did_trigger,
            "trigger_correct": trigger_ok,
            "bash_commands":   parsed["bash_commands"],
            "files_written":   parsed["files_written"],
            "skill_calls":     parsed["skill_calls"],
            "process_checks":  process_results,
            "scoring":         scoring,
            "usage":           parsed.get("usage", {}),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }
        all_results.append(result)

        out_dir = RESULTS_DIR / skill
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{run_id}.result.json").write_text(json.dumps(result, indent=2))

        t_icon    = "✓" if trigger_ok else "✗"
        score_str = f"score={scoring['score']}/100" if process_results else "—"
        print(f"  {t_icon} did_trigger={did_trigger}  skill_calls={parsed['skill_calls']}  {score_str}")
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
    print(f"SUMMARY  skill={skill}  platform=copilot")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Results in       : {RESULTS_DIR / skill}/")

    summary = {
        "skill": skill, "platform": "copilot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger_accuracy": {"correct": trigger_correct, "total": total},
        "false_positives":  [r["run_id"] for r in false_pos],
        "false_negatives":  [r["run_id"] for r in false_neg],
        "process_avg_score": avg_score,
        "total_blocking_failures": total_blocking,
        "runs": [{"run_id": r["run_id"], "trigger_correct": r["trigger_correct"],
                  "score": r["scoring"]["score"]} for r in all_results],
    }
    (RESULTS_DIR / skill / "summary.json").write_text(json.dumps(summary, indent=2))

    if false_pos or false_neg or total_blocking > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
