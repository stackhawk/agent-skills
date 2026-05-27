#!/usr/bin/env python3
"""
Gemini CLI eval harness for StackHawk agent skills.

Uses `gemini -p --output-format stream-json` (Gemini's headless CLI).
Skills are loaded from the StackHawk extension linked via:
    gemini extensions link /path/to/agent-skills

Usage:
    python3 evals/harnesses/gemini/run-evals.py --skill hawkscan
    python3 evals/harnesses/gemini/run-evals.py --skill api
    python3 evals/harnesses/gemini/run-evals.py --skill hawkscan --id hw-07
    python3 evals/harnesses/gemini/run-evals.py --skill hawkscan --dry-run
    python3 evals/harnesses/gemini/run-evals.py --skill hawkscan --full-auto   # execute commands

Requirements:
    - Gemini CLI installed: npm install -g @google/gemini-cli
    - API key: export GEMINI_API_KEY=<key>
    - Extension linked: gemini extensions link /path/to/agent-skills
    - Run from the agent-skills repo root

Notes:
    - Gemini stream-json format differs from Claude Code; parse_stream() may need
      adjustment for your Gemini CLI version. Run --dry-run to verify install,
      then test with --id hw-01 and inspect the raw JSONL in results/ to tune.
    - Model: defaults to gemini-2.5-pro. Override with --model gemini-2.5-flash.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import shutil
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
# Trigger signals — same split-signal approach as Claude Code harness.
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
        # Claude Code evaluation-format variants (if Gemini uses that style)
        "hawkscan:hawkscan`: yes", "hawkscan:hawkscan` — yes",
        "hawkscan:hawkscan**: yes","hawkscan:hawkscan** — yes",
        "hawkscan:hawkscan: yes",  "hawkscan:hawkscan — yes",
        "hawkscan:hawkscan - yes", "hawkscan:hawkscan - **yes",
        "hawkscan** - yes",        "hawkscan** — yes",
        "hawkscan**: yes",         "hawkscan: yes",
        "hawkscan — yes",          "hawkscan - yes",
        # Narrative-style (agent says this instead of evaluating)
        "hawkscan skill",
        "autonomous security scan",
        "dast scan after code", "dast scan triggered", "dast scan required",
        "security scan required", "security scan after",
        "run the security scan",  "running the hawkscan",
    ],
    "api": [
        # Claude Code evaluation-format variants
        "stackhawk-api:api`: yes", "stackhawk-api:api` — yes",
        "stackhawk-api:api**: yes","stackhawk-api:api** — yes",
        "stackhawk-api:api: yes",  "stackhawk-api:api — yes",
        "stackhawk-api:api - yes",
        "stackhawk-api**: yes",    "stackhawk-api** — yes",
        "stackhawk-api: yes",      "stackhawk-api — yes",
        "stackhawk-api - yes",
        # Narrative-style
        "stackhawk api skill",
        "stackhawk api",
        "api skill to",
        "security posture",
        "untriaged findings",
        "scan history",
        "findings across",
    ],
}

# ---------------------------------------------------------------------------
# Stream-json parsing — verified against Gemini CLI v0.43.x stream-json format:
#   {"type":"init", ...}
#   {"type":"message","role":"user","content":"..."}
#   {"type":"message","role":"assistant","content":"...","delta":true}  ← streaming
#   {"type":"tool_use","tool_name":"run_shell_command","parameters":{"command":"..."}}
#   {"type":"tool_result","tool_id":"...","status":"success"}
#   {"type":"result","status":"success","stats":{"total_tokens":N,...}}
# ---------------------------------------------------------------------------

def parse_stream(jsonl: str) -> dict:
    bash_commands: list[str] = []
    files_written: list[str] = []
    output_text = ""
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

        # Assistant text — delta streaming chunks
        if etype == "message" and event.get("role") == "assistant":
            content = event.get("content", "")
            if isinstance(content, str):
                output_text += content
                if not event.get("delta"):
                    output_text += "\n"
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        output_text += block.get("text", "")

        # Tool calls — run_shell_command carries the command in parameters
        elif etype == "tool_use":
            name = event.get("tool_name", "")
            params = event.get("parameters", {})
            if name in ("run_shell_command", "shell", "bash", "execute_bash",
                        "execute_code", "run_code", "terminal"):
                cmd = (params.get("command") or params.get("code") or
                       params.get("cmd") or "")
                if cmd:
                    bash_commands.append(cmd)
            elif name in ("write_file", "create_file", "write_to_file"):
                path = params.get("path") or params.get("file_path") or ""
                if path:
                    files_written.append(path)

        # Claude Code-style assistant block (in case Gemini mimics that format)
        elif etype == "assistant":
            pass  # kept for forward-compat if format changes

        # Final result carries token stats
        elif etype == "result":
            stats = event.get("stats", {})
            if stats:
                usage = {
                    "inputTokens":  stats.get("input_tokens", 0),
                    "outputTokens": stats.get("output_tokens", 0),
                    "totalTokens":  stats.get("total_tokens", 0),
                }
            if event.get("status") == "error":
                error = str(event.get("error", "unknown error"))

        elif etype == "error":
            error = event.get("message", "unknown error")

    return {
        "bash_commands":  bash_commands,
        "files_written":  files_written,
        "output_text":    output_text.strip(),
        "usage":          usage,
        "error":          error,
    }


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

def detect_trigger(parsed: dict, skill: str) -> bool:
    cli_haystack = " ".join(parsed["bash_commands"]).lower()
    if any(s.lower() in cli_haystack for s in CLI_SIGNALS.get(skill, [])):
        return True
    text_haystack = parsed["output_text"].lower()
    return any(s.lower() in text_haystack for s in INVOCATION_SIGNALS.get(skill, []))


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
# Run gemini
# ---------------------------------------------------------------------------

def run_gemini(
    prompt: str,
    skill: str,
    run_id: str,
    full_auto: bool = False,
    model: str | None = None,
) -> tuple[dict, int]:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_"))
    try:
        cmd = [
            "gemini",
            "-p", prompt,
            "--output-format", "stream-json",
            "--skip-trust",
        ]
        if model:
            cmd += ["-m", model]
        if full_auto:
            cmd += ["--approval-mode", "yolo"]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,   # 15 min — Gemini rate-limit retries can take 5-10 min per prompt
            cwd=str(tmpdir),
            env={**os.environ},
        )

        trace_dir = RESULTS_DIR / skill
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"{run_id}.jsonl").write_text(proc.stdout)

        parsed = parse_stream(proc.stdout)
        if proc.returncode != 0 and not parsed["output_text"]:
            stderr = proc.stderr.strip()
            if stderr:
                parsed["error"] = stderr[:200]

        return parsed, proc.returncode

    except subprocess.TimeoutExpired:
        return {"bash_commands": [], "files_written": [], "output_text": "",
                "usage": {}, "error": "timeout"}, 1
    except FileNotFoundError:
        print("ERROR: 'gemini' CLI not found. Run: npm install -g @google/gemini-cli",
              file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gemini CLI eval harness for StackHawk agent skills",
    )
    parser.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id", dest="prompt_id", metavar="RUN_ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-auto", action="store_true",
                        help="Pass --approval-mode yolo so agent executes commands")
    parser.add_argument("--model", metavar="MODEL_ID", default=None,
                        help="Gemini model ID override (default: gemini CLI's configured default, currently gemini-3-flash-preview)")
    args = parser.parse_args()

    # Auth: Gemini supports GEMINI_API_KEY env var, Google Cloud credentials (GOOGLE_GENAI_USE_GCA),
    # or stored OAuth via `gemini` login. The CLI will error naturally if not authenticated.
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

    mode = "full-auto" if args.full_auto else "observe"
    model_label = f"  |  Model: {args.model}" if args.model else ""
    print(f"\nSkill: {skill}  |  Platform: gemini  |  Mode: {mode}{model_label}  |  Prompts: {len(prompts)}")
    if args.dry_run:
        print("[dry-run — no gemini calls]")
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

        parsed, _exit = run_gemini(
            prompt, skill, run_id,
            full_auto=args.full_auto,
            model=args.model,
        )

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
            "platform":        "gemini",
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
            "usage":           parsed.get("usage", {}),
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
    print(f"SUMMARY  skill={skill}  platform=gemini")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Results in       : {RESULTS_DIR / skill}/")

    summary = {
        "skill": skill, "platform": "gemini",
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
