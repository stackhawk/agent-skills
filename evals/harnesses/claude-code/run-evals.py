#!/usr/bin/env python3
"""
Claude Code eval harness for StackHawk agent skills.

Usage:
    python3 run-evals.py --skill hawkscan          # all prompts
    python3 run-evals.py --skill api               # all prompts
    python3 run-evals.py --skill hawkscan --id hw-07    # single prompt
    python3 run-evals.py --skill hawkscan --dry-run     # print prompts, no claude calls
    python3 run-evals.py --skill hawkscan --full-auto   # allow agent to execute commands
    python3 run-evals.py --skill hawkscan --rubric      # also run qualitative rubric grader
    python3 run-evals.py --skill hawkscan --bare        # CI mode: ANTHROPIC_API_KEY only, no keychain

Requirements:
    - claude CLI installed and authenticated (https://claude.ai/code)
    - Run from the agent-skills repo root (plugin dirs are auto-detected)

Output:
    evals/harnesses/claude-code/results/<skill>/<run-id>.jsonl       raw trace
    evals/harnesses/claude-code/results/<skill>/<run-id>.result.json scored result
    evals/harnesses/claude-code/results/<skill>/summary.json         run summary
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
EVALS_DIR = HARNESS_DIR.parent.parent
REPO_ROOT = EVALS_DIR.parent
RESULTS_DIR = HARNESS_DIR / "results"

# ---------------------------------------------------------------------------
# Trigger signals
# Any of these appearing in bash commands or output text means the skill fired.
# ---------------------------------------------------------------------------
# CLI signals — checked against bash_commands only (prevents documentation content
# from creating false positives when the agent writes README/guides about HawkScan).
CLI_SIGNALS = {
    "hawkscan": [
        "hawk scan",
        "hawk validate",
        "hawk rescan",
        # "hawk version" intentionally excluded: running 'hawk version' alone is common
        # for installation-check tasks and would cause false positives. The preflight
        # workflow always runs 'hawk config --help' in the same command, so 'hawk config'
        # below is sufficient to distinguish scan-intent from install-check tasks.
        "hawk config",
        "hawk create app",
        "hawk init",
        "hawk perch",
    ],
    "api": [
        "hawkop scan",
        "hawkop app",
        "hawkop org",
        "hawkop env",
        "hawkop status",
        "hawkop init",
        "/api/v1/scan",
        "/api/v2/org",
        "hawk_api GET",
    ],
}

# Invocation signals — checked against output_text only. Catches contextual prompts
# where the agent correctly identifies the skill should trigger and says so explicitly,
# but can't reach the CLI workflow (empty working dir, no running app, etc.).
#
# These are intentionally specific to action-intent phrases, NOT the generic
# "hawkscan:hawkscan: yes" pattern (which also fires on educational/informational
# responses where the agent answers "what does HawkScan detect?" type questions).
INVOCATION_SIGNALS = {
    "hawkscan": [
        # Generic YES-evaluation signals — catch any run where the agent explicitly
        # evaluates hawkscan as YES regardless of phrasing. Models vary in their markdown
        # formatting: backtick (`` `hawkscan:hawkscan` ``), bold (**hawkscan:hawkscan**),
        # or plain text. Each produces a different character sequence around `: YES`.
        # Safe because SKILL.md now instructs NO for educational questions (hw-20),
        # doc-only changes (hw-16/17/18), installation tasks (hw-19), and explicit skips.
        "hawkscan:hawkscan`: yes",   # "`hawkscan:hawkscan`: YES" — backtick + colon
        "hawkscan:hawkscan` — yes",  # "`hawkscan:hawkscan` — YES" — backtick + dash
        "hawkscan:hawkscan**: yes",  # "**hawkscan:hawkscan**: YES" — bold + colon
        "hawkscan:hawkscan** — yes", # "**hawkscan:hawkscan** — YES" — bold + dash
        "hawkscan:hawkscan: yes",    # "hawkscan:hawkscan: YES" — plain colon
        "hawkscan:hawkscan — yes",   # "hawkscan:hawkscan — YES" — plain dash
        # Specific action-intent phrases as belt-and-suspenders for unusual formats
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

# ---------------------------------------------------------------------------
# Stream-json parsing
# ---------------------------------------------------------------------------

def parse_stream(jsonl: str) -> dict:
    """Extract structured data from a claude --output-format stream-json run."""
    bash_commands: list[str] = []
    files_written: list[str] = []
    files_edited: list[str] = []
    output_text = ""
    cost_usd = 0.0
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
                btype = block.get("type", "")
                if btype == "text":
                    output_text += block.get("text", "") + "\n"
                elif btype == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    if name == "Bash":
                        cmd = inp.get("command", "")
                        if cmd:
                            bash_commands.append(cmd)
                    elif name == "Write":
                        path = inp.get("file_path", "")
                        if path:
                            files_written.append(path)
                    elif name == "Edit":
                        path = inp.get("file_path", "")
                        if path:
                            files_edited.append(path)

        elif etype == "result":
            cost_usd = event.get("cost_usd") or 0.0
            output_text += event.get("result", "")
            if event.get("subtype") == "error_during_execution":
                error = event.get("result", "unknown error")

    return {
        "bash_commands": bash_commands,
        "files_written": files_written,
        "files_edited": files_edited,
        "output_text": output_text.strip(),
        "cost_usd": cost_usd,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

def detect_trigger(parsed: dict, skill: str) -> bool:
    # CLI signals are checked only against actual bash commands executed — prevents
    # documentation content (README guides, educational answers) from triggering.
    cli_haystack = " ".join(parsed["bash_commands"]).lower()
    if any(s.lower() in cli_haystack for s in CLI_SIGNALS.get(skill, [])):
        return True

    # Invocation signals are checked only against output text — catches cases where
    # the agent evaluated the skill as YES but couldn't run CLI commands (e.g. empty
    # working dir, permission blocks on hawkop, no running app).
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
    all_files = " ".join(parsed["files_written"] + parsed["files_edited"]).lower()

    results = []
    for check in checks:
        ctype = check.get("type", "command_executed")
        signals = [s.lower() for s in check.get("signals", [])]
        antis = [a.lower() for a in check.get("anti_patterns", [])]

        signal_hit = next((s for s in signals if s in haystack), None)
        anti_hit = next((a for a in antis if a in haystack), None)

        if ctype in ("command_negative", "file_content_negative", "output_negative"):
            passed = anti_hit is None
        elif ctype == "file_absent":
            target = check.get("target_file", "").lower()
            passed = target not in all_files
        elif ctype == "conditional_command":
            # Only enforce when the condition's keyword appears in the trace.
            # Extract the keyword inside single quotes from the condition string,
            # e.g. "stackhawk.yml contains 'authentication:'" → "authentication:"
            import re as _re
            condition_str = check.get("condition", "")
            m = _re.search(r"'([^']+)'", condition_str)
            condition_keyword = m.group(1).lower() if m else None
            if condition_keyword and condition_keyword not in haystack:
                passed = True  # condition not met — check is not applicable
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
            "id": check["id"],
            "pass": passed,
            "severity": check.get("severity", "warning"),
            "signal_found": signal_hit,
            "anti_found": anti_hit,
        })

    return results


def score_checks(results: list[dict]) -> dict:
    blocking_failed = sum(1 for r in results if not r["pass"] and r["severity"] == "blocking")
    warning_failed  = sum(1 for r in results if not r["pass"] and r["severity"] == "warning")
    score = max(0, 100 - blocking_failed * 15 - warning_failed * 5)
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["pass"]),
        "blocking_failed": blocking_failed,
        "warning_failed": warning_failed,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Run claude -p
# ---------------------------------------------------------------------------

def run_claude(
    prompt: str,
    skill: str,
    run_id: str,
    plugin_dirs: list[str],
    full_auto: bool = False,
    bare: bool = False,
    max_budget: float = 0.20,
    model: str | None = None,
) -> tuple[dict, int]:
    # Each eval runs in a fresh temp dir so there is no state leakage.
    tmpdir = tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_")
    try:
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--max-budget-usd", str(max_budget),
        ]
        if model:
            cmd += ["--model", model]
        for pd in plugin_dirs:
            cmd += ["--plugin-dir", pd]
        if full_auto:
            cmd.append("--dangerously-skip-permissions")
        if bare:
            cmd.append("--bare")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmpdir,
        )

        trace_dir = RESULTS_DIR / skill
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"{run_id}.jsonl").write_text(proc.stdout)

        return parse_stream(proc.stdout), proc.returncode

    except subprocess.TimeoutExpired:
        return {
            "bash_commands": [], "files_written": [], "files_edited": [],
            "output_text": "", "cost_usd": 0.0, "error": "timeout",
        }, 1
    except FileNotFoundError:
        print(
            "ERROR: 'claude' CLI not found. "
            "Install Claude Code (https://claude.ai/code) and ensure it is in PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rubric grader (qualitative, model-assisted, optional)
# ---------------------------------------------------------------------------

def run_rubric_grader(
    parsed: dict,
    skill: str,
    run_id: str,
    plugin_dirs: list[str],
    bare: bool = False,
) -> dict | None:
    rubric_path = EVALS_DIR / skill / "rubric-items.json"
    schema_path = EVALS_DIR / "rubric-schema.json"
    if not rubric_path.exists() or not schema_path.exists():
        print("  [rubric] rubric-items.json or rubric-schema.json not found — skipping",
              file=sys.stderr)
        return None

    rubric_data = json.loads(rubric_path.read_text())
    schema = json.loads(schema_path.read_text())

    grader_prompt = f"""{rubric_data['grader_prompt']}

## Bash Commands Executed:
{json.dumps(parsed['bash_commands'], indent=2)}

## Files Written/Edited:
{json.dumps(parsed['files_written'] + parsed['files_edited'], indent=2)}

## Agent Output (first 4000 chars):
{parsed['output_text'][:4000]}

## Rubric Checks to Grade:
{json.dumps(rubric_data['checks'], indent=2)}

Populate the JSON result with:
  skill = "{skill}"
  run_id = "{run_id}"
  overall_pass = true if all checks pass and score >= 70
  score = 0-100
  checks = one entry per check id listed above"""

    cmd = [
        "claude", "-p", grader_prompt,
        "--output-format", "json",
        "--no-session-persistence",
        "--json-schema", json.dumps(schema),
        "--max-budget-usd", "0.10",
    ]
    for pd in plugin_dirs:
        cmd += ["--plugin-dir", pd]
    if bare:
        cmd.append("--bare")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        envelope = json.loads(proc.stdout)
        # --output-format json wraps the response: {"result": "<json_string>", ...}
        raw_result = envelope.get("result", "{}")
        if isinstance(raw_result, dict):
            return raw_result
        return json.loads(raw_result)
    except Exception as exc:
        print(f"  [rubric] grader failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Code eval harness for StackHawk agent skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id", dest="prompt_id", metavar="RUN_ID",
                        help="Run a single prompt by id (e.g. hw-07)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling claude")
    parser.add_argument("--rubric", action="store_true",
                        help="Run qualitative rubric grader after process checks (extra cost + time)")
    parser.add_argument("--full-auto", action="store_true",
                        help="Pass --dangerously-skip-permissions so the agent can execute commands")
    parser.add_argument("--bare", action="store_true",
                        help="Pass --bare to claude: ANTHROPIC_API_KEY only, no keychain/hooks/CLAUDE.md (recommended for CI)")
    parser.add_argument("--max-budget", type=float, default=0.20, metavar="USD",
                        help="Max spend per eval run in USD (default: 0.20)")
    parser.add_argument("--plugin-dir", action="append", dest="plugin_dirs",
                        help="Plugin dir to load; auto-detected from repo root if omitted")
    parser.add_argument("--model", metavar="MODEL_ID",
                        help="Override the Claude model (e.g. claude-haiku-4-5-20251001, claude-sonnet-4-6)")
    args = parser.parse_args()

    skill = args.skill
    plugin_dirs = args.plugin_dirs or [str(REPO_ROOT / "plugins" / skill)]

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
    if args.bare:
        mode += "+bare"
    model_label = f"  |  Model: {args.model}" if args.model else ""
    print(f"\nSkill: {skill}  |  Platform: claude-code  |  Mode: {mode}{model_label}  |  Prompts: {len(prompts)}")
    if args.dry_run:
        print("[dry-run — no claude calls]")
    print("─" * 68)

    all_results = []
    total_cost = 0.0

    for row in prompts:
        run_id        = row["id"]
        prompt        = row["prompt"]
        should_trigger = row["should_trigger"].lower() == "true"
        itype         = row.get("invocation_type", "")

        print(f"\n[{run_id}] {itype:<12}  trigger={'Y' if should_trigger else 'N'}")
        print(f"  {prompt[:92]}{'…' if len(prompt) > 92 else ''}")

        if args.dry_run:
            print("  → skipped")
            continue

        parsed, _exit = run_claude(
            prompt, skill, run_id, plugin_dirs,
            full_auto=args.full_auto,
            bare=args.bare,
            max_budget=args.max_budget,
            model=args.model,
        )
        total_cost += parsed.get("cost_usd", 0.0)

        if parsed.get("error"):
            print(f"  ERROR: {parsed['error']}")

        did_trigger  = detect_trigger(parsed, skill)
        trigger_ok   = did_trigger == should_trigger

        process_results: list[dict] = []
        scoring = {"total": 0, "passed": 0, "blocking_failed": 0, "warning_failed": 0, "score": 0}
        if should_trigger and did_trigger:
            process_results = run_process_checks(parsed, checks)
            scoring = score_checks(process_results)

        rubric_result = None
        if args.rubric and should_trigger and did_trigger:
            print("  [rubric] grading…", end=" ", flush=True)
            rubric_result = run_rubric_grader(parsed, skill, run_id, plugin_dirs, bare=args.bare)
            print(f"score={rubric_result.get('score', '?')}" if rubric_result else "failed")

        result = {
            "platform": "claude-code",
            "skill": skill,
            "run_id": run_id,
            "prompt": prompt,
            "should_trigger": should_trigger,
            "did_trigger": did_trigger,
            "trigger_correct": trigger_ok,
            "bash_commands": parsed["bash_commands"],
            "files_written": parsed["files_written"],
            "process_checks": process_results,
            "scoring": scoring,
            "rubric_result": rubric_result,
            "cost_usd": parsed.get("cost_usd", 0.0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        all_results.append(result)

        out_dir = RESULTS_DIR / skill
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{run_id}.result.json").write_text(json.dumps(result, indent=2))

        t_icon   = "✓" if trigger_ok else "✗"
        score_str = f"score={scoring['score']}/100" if process_results else "—"
        print(f"  {t_icon} did_trigger={did_trigger}  {score_str}  ${parsed.get('cost_usd', 0):.3f}")

        for pr in process_results:
            if not pr["pass"] and pr["severity"] == "blocking":
                print(f"    BLOCKING FAIL: {pr['id']}")

    if args.dry_run or not all_results:
        return

    # ── Final summary ──────────────────────────────────────────────────────
    trigger_correct = sum(1 for r in all_results if r["trigger_correct"])
    total = len(all_results)
    false_pos = [r for r in all_results if not r["should_trigger"] and r["did_trigger"]]
    false_neg = [r for r in all_results if r["should_trigger"] and not r["did_trigger"]]
    process_runs = [r for r in all_results if r["process_checks"]]
    avg_score = (sum(r["scoring"]["score"] for r in process_runs) // len(process_runs)
                 if process_runs else None)
    total_blocking = (sum(r["scoring"]["blocking_failed"] for r in process_runs)
                      if process_runs else 0)

    print("\n" + "═" * 68)
    print(f"SUMMARY  skill={skill}  platform=claude-code")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Total cost       : ${total_cost:.3f}")
    print(f"  Results in       : {RESULTS_DIR / skill}/")

    summary = {
        "skill": skill,
        "platform": "claude-code",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger_accuracy": {"correct": trigger_correct, "total": total},
        "false_positives": [r["run_id"] for r in false_pos],
        "false_negatives": [r["run_id"] for r in false_neg],
        "process_avg_score": avg_score,
        "total_blocking_failures": total_blocking,
        "total_cost_usd": round(total_cost, 4),
        "runs": [
            {
                "run_id": r["run_id"],
                "trigger_correct": r["trigger_correct"],
                "score": r["scoring"]["score"],
                "cost_usd": r["cost_usd"],
            }
            for r in all_results
        ],
    }
    (RESULTS_DIR / skill / "summary.json").write_text(json.dumps(summary, indent=2))

    # ── GitHub Actions step summary ────────────────────────────────────────
    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_path:
        _write_step_summary(
            step_summary_path, skill, all_results,
            false_pos, false_neg, avg_score, total_blocking, total_cost,
        )

    # ── Exit non-zero for CI on any regression ─────────────────────────────
    if false_pos or false_neg or total_blocking > 0:
        sys.exit(1)


def _write_step_summary(
    path: str,
    skill: str,
    results: list[dict],
    false_pos: list[dict],
    false_neg: list[dict],
    avg_score: int | None,
    total_blocking: int,
    total_cost: float,
) -> None:
    correct = sum(1 for r in results if r["trigger_correct"])
    total = len(results)
    trigger_icon = "✅" if correct == total else "❌"
    score_icon = "✅" if (avg_score or 0) >= 70 and total_blocking == 0 else "❌"

    lines = [
        f"## Skill Eval: `{skill}` (claude-code)\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Trigger accuracy | {trigger_icon} {correct}/{total} |",
    ]
    if false_pos:
        lines.append(f"| False positives | ⚠️ {', '.join(r['run_id'] for r in false_pos)} |")
    if false_neg:
        lines.append(f"| False negatives | ⚠️ {', '.join(r['run_id'] for r in false_neg)} |")
    if avg_score is not None:
        lines.append(f"| Process avg score | {score_icon} {avg_score}/100 |")
        lines.append(f"| Blocking failures | {'❌' if total_blocking else '✅'} {total_blocking} |")
    lines.append(f"| Total cost | ${total_cost:.3f} |")
    lines.append("")

    # Per-run table
    lines += [
        "<details><summary>Per-run results</summary>\n",
        "| ID | Trigger | Score | Cost |",
        "|---|---|---|---|",
    ]
    for r in results:
        t = "✅" if r["trigger_correct"] else "❌"
        score = r["scoring"]["score"] if r["process_checks"] else "—"
        lines.append(f"| {r['run_id']} | {t} | {score} | ${r['cost_usd']:.3f} |")
    lines.append("\n</details>\n")

    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
