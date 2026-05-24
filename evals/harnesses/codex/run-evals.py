#!/usr/bin/env python3
"""
Codex eval harness for StackHawk agent skills.

Usage:
    python3 run-evals.py --skill hawkscan          # all prompts
    python3 run-evals.py --skill api               # all prompts
    python3 run-evals.py --skill hawkscan --id hw-07    # single prompt
    python3 run-evals.py --skill hawkscan --dry-run     # print prompts, no codex calls
    python3 run-evals.py --skill hawkscan --rubric      # also run qualitative rubric grader

Requirements:
    - codex CLI installed and authenticated (https://openai.com/codex)
    - Run from the agent-skills repo root

Output:
    evals/harnesses/codex/results/<skill>/<run-id>.jsonl       raw JSONL trace
    evals/harnesses/codex/results/<skill>/<run-id>.result.json scored result
    evals/harnesses/codex/results/<skill>/summary.json         run summary
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

# ---------------------------------------------------------------------------
# Trigger signals
# ---------------------------------------------------------------------------
TRIGGER_SIGNALS = {
    "hawkscan": [
        "hawk scan",
        "hawk validate",
        "hawk rescan",
        "hawk version",
        "hawk config",
        "hawk create app",
        "hawk init",
        "hawk perch",
        "stackhawk.yml",
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

# ---------------------------------------------------------------------------
# JSONL parsing
# Codex --json event stream: item.started / item.completed / turn.completed
# ---------------------------------------------------------------------------

def parse_stream(jsonl: str) -> dict:
    commands: list[str] = []
    output_text = ""
    input_tokens = 0
    output_tokens = 0
    error = None

    seen_commands: set[str] = set()

    for line in jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "item.started":
            item = event.get("item", {})
            if item.get("type") == "command_execution":
                cmd = item.get("command", "")
                # Deduplicate: item.started fires before item.completed for the same cmd
                if cmd and cmd not in seen_commands:
                    commands.append(cmd)
                    seen_commands.add(cmd)

        elif etype == "item.completed":
            item = event.get("item", {})
            # Capture any assistant message text
            if item.get("type") == "message":
                content = item.get("content", "")
                if isinstance(content, str):
                    output_text += content + "\n"
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            output_text += block.get("text", "") + "\n"

        elif etype == "turn.completed":
            usage = event.get("usage", {})
            input_tokens  += usage.get("input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)

        elif etype == "error":
            error = event.get("message", "unknown error")

    return {
        "bash_commands": commands,
        "files_written": [],  # populated by scanning tmpdir after run
        "files_edited":  [],
        "output_text":   output_text.strip(),
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "error":         error,
    }


def _setup_skill_in_dir(skill: str, target_dir: Path) -> None:
    """Copy skill SKILL.md + references into .codex/skills/<skill>/ for discovery."""
    src = REPO_ROOT / "plugins" / skill / "skills" / skill
    dst = target_dir / ".codex" / "skills" / skill
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

def detect_trigger(parsed: dict, skill: str) -> bool:
    signals = TRIGGER_SIGNALS.get(skill, [])
    haystack = " ".join([
        *parsed["bash_commands"],
        *parsed["files_written"],
        parsed["output_text"],
    ]).lower()
    return any(s.lower() in haystack for s in signals)


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
    score = max(0, 100 - blocking_failed * 15 - warning_failed * 5)
    return {
        "total":            len(results),
        "passed":           sum(1 for r in results if r["pass"]),
        "blocking_failed":  blocking_failed,
        "warning_failed":   warning_failed,
        "score":            score,
    }


# ---------------------------------------------------------------------------
# Run codex exec
# ---------------------------------------------------------------------------

def run_codex(
    prompt: str,
    skill: str,
    run_id: str,
    full_auto: bool = True,
    max_budget: float = 0.20,
) -> tuple[dict, int]:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"hawkeval_{run_id}_"))
    try:
        _setup_skill_in_dir(skill, tmpdir)

        cmd = ["codex", "exec", "--json"]
        if full_auto:
            cmd.append("--full-auto")
        cmd.append(prompt)

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

        parsed = parse_stream(proc.stdout)

        # Scan tmpdir for files created during the run (more reliable than JSONL parsing)
        created = [
            str(p.relative_to(tmpdir))
            for p in tmpdir.rglob("*")
            if p.is_file() and not str(p).startswith(str(tmpdir / ".codex"))
        ]
        parsed["files_written"] = created

        return parsed, proc.returncode

    except subprocess.TimeoutExpired:
        return {
            "bash_commands": [], "files_written": [], "files_edited": [],
            "output_text": "", "input_tokens": 0, "output_tokens": 0, "error": "timeout",
        }, 1
    except FileNotFoundError:
        print(
            "ERROR: 'codex' CLI not found. "
            "Install the Codex CLI and ensure it is in PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rubric grader
# Uses: codex exec "<prompt>" --output-schema <schema> -o <output_file>
# ---------------------------------------------------------------------------

def run_rubric_grader(parsed: dict, skill: str, run_id: str) -> dict | None:
    rubric_path = EVALS_DIR / skill / "rubric-items.json"
    schema_path = EVALS_DIR / "rubric-schema.json"
    if not rubric_path.exists() or not schema_path.exists():
        return None

    rubric_data = json.loads(rubric_path.read_text())

    grader_prompt = f"""{rubric_data['grader_prompt']}

## Commands Executed:
{json.dumps(parsed['bash_commands'], indent=2)}

## Files Created:
{json.dumps(parsed['files_written'], indent=2)}

## Agent Output (first 4000 chars):
{parsed['output_text'][:4000]}

## Rubric Checks to Grade:
{json.dumps(rubric_data['checks'], indent=2)}

Populate: skill="{skill}", run_id="{run_id}", overall_pass, score 0-100, checks array."""

    tmpdir = Path(tempfile.mkdtemp(prefix=f"hawkrubric_{run_id}_"))
    try:
        output_file = tmpdir / "rubric_result.json"
        cmd = [
            "codex", "exec",
            grader_prompt,
            "--output-schema", str(schema_path),
            "-o", str(output_file),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(tmpdir))

        if output_file.exists():
            return json.loads(output_file.read_text())
        return None
    except Exception as exc:
        print(f"  [rubric] grader failed: {exc}", file=sys.stderr)
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Codex eval harness for StackHawk agent skills",
    )
    parser.add_argument("--skill", required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id", dest="prompt_id", metavar="RUN_ID",
                        help="Run a single prompt by id (e.g. hw-07)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling codex")
    parser.add_argument("--rubric", action="store_true",
                        help="Run qualitative rubric grader after process checks (extra cost)")
    parser.add_argument("--no-full-auto", action="store_true",
                        help="Run without --full-auto (restricts filesystem access)")
    parser.add_argument("--max-budget", type=float, default=0.20, metavar="USD",
                        help="Max spend per eval run in USD (default: 0.20)")
    args = parser.parse_args()

    skill = args.skill
    full_auto = not args.no_full_auto

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

    mode = "full-auto" if full_auto else "sandbox"
    print(f"\nSkill: {skill}  |  Platform: codex  |  Mode: {mode}  |  Prompts: {len(prompts)}")
    if args.dry_run:
        print("[dry-run — no codex calls]")
    print("─" * 68)

    all_results = []
    total_cost = 0.0

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

        parsed, _exit = run_codex(
            prompt, skill, run_id,
            full_auto=full_auto,
            max_budget=args.max_budget,
        )

        # Codex doesn't report USD cost directly; estimate from token usage
        tokens = parsed.get("input_tokens", 0) + parsed.get("output_tokens", 0)
        est_cost = tokens * 0.000015  # rough estimate
        total_cost += est_cost

        if parsed.get("error"):
            print(f"  ERROR: {parsed['error']}")

        did_trigger = detect_trigger(parsed, skill)
        trigger_ok  = did_trigger == should_trigger

        process_results: list[dict] = []
        scoring = {"total": 0, "passed": 0, "blocking_failed": 0, "warning_failed": 0, "score": 0}
        if should_trigger and did_trigger:
            process_results = run_process_checks(parsed, checks)
            scoring = score_checks(process_results)

        rubric_result = None
        if args.rubric and should_trigger and did_trigger:
            print("  [rubric] grading…", end=" ", flush=True)
            rubric_result = run_rubric_grader(parsed, skill, run_id)
            print(f"score={rubric_result.get('score', '?')}" if rubric_result else "failed")

        result = {
            "platform":       "codex",
            "skill":          skill,
            "run_id":         run_id,
            "prompt":         prompt,
            "should_trigger": should_trigger,
            "did_trigger":    did_trigger,
            "trigger_correct": trigger_ok,
            "bash_commands":  parsed["bash_commands"],
            "files_written":  parsed["files_written"],
            "process_checks": process_results,
            "scoring":        scoring,
            "rubric_result":  rubric_result,
            "tokens":         {"input": parsed.get("input_tokens", 0), "output": parsed.get("output_tokens", 0)},
            "timestamp":      datetime.now(timezone.utc).isoformat(),
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

    # ── Summary ────────────────────────────────────────────────────────────
    trigger_correct = sum(1 for r in all_results if r["trigger_correct"])
    total      = len(all_results)
    false_pos  = [r for r in all_results if not r["should_trigger"] and r["did_trigger"]]
    false_neg  = [r for r in all_results if r["should_trigger"] and not r["did_trigger"]]
    proc_runs  = [r for r in all_results if r["process_checks"]]
    avg_score  = (sum(r["scoring"]["score"] for r in proc_runs) // len(proc_runs)
                  if proc_runs else None)
    total_blocking = sum(r["scoring"]["blocking_failed"] for r in proc_runs) if proc_runs else 0

    print("\n" + "═" * 68)
    print(f"SUMMARY  skill={skill}  platform=codex")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Results in       : {RESULTS_DIR / skill}/")

    summary = {
        "skill":    skill,
        "platform": "codex",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger_accuracy": {"correct": trigger_correct, "total": total},
        "false_positives":  [r["run_id"] for r in false_pos],
        "false_negatives":  [r["run_id"] for r in false_neg],
        "process_avg_score": avg_score,
        "total_blocking_failures": total_blocking,
        "runs": [
            {"run_id": r["run_id"], "trigger_correct": r["trigger_correct"], "score": r["scoring"]["score"]}
            for r in all_results
        ],
    }
    (RESULTS_DIR / skill / "summary.json").write_text(json.dumps(summary, indent=2))

    # ── GitHub Actions step summary ─────────────────────────────────────────
    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_path:
        _write_step_summary(step_summary_path, skill, all_results, false_pos, false_neg, avg_score, total_blocking)

    if false_pos or false_neg or total_blocking > 0:
        sys.exit(1)


def _write_step_summary(
    path: str, skill: str, results: list[dict],
    false_pos: list[dict], false_neg: list[dict],
    avg_score: int | None, total_blocking: int,
) -> None:
    correct = sum(1 for r in results if r["trigger_correct"])
    total = len(results)
    trigger_icon = "✅" if correct == total else "❌"
    score_icon   = "✅" if (avg_score or 0) >= 70 and total_blocking == 0 else "❌"

    lines = [
        f"## Skill Eval: `{skill}` (codex)\n",
        "| Metric | Value |", "|---|---|",
        f"| Trigger accuracy | {trigger_icon} {correct}/{total} |",
    ]
    if false_pos:
        lines.append(f"| False positives | ⚠️ {', '.join(r['run_id'] for r in false_pos)} |")
    if false_neg:
        lines.append(f"| False negatives | ⚠️ {', '.join(r['run_id'] for r in false_neg)} |")
    if avg_score is not None:
        lines.append(f"| Process avg score | {score_icon} {avg_score}/100 |")
        lines.append(f"| Blocking failures | {'❌' if total_blocking else '✅'} {total_blocking} |")
    lines.append("")

    lines += [
        "<details><summary>Per-run results</summary>\n",
        "| ID | Trigger | Score |", "|---|---|---|",
    ]
    for r in results:
        t = "✅" if r["trigger_correct"] else "❌"
        score = r["scoring"]["score"] if r["process_checks"] else "—"
        lines.append(f"| {r['run_id']} | {t} | {score} |")
    lines.append("\n</details>\n")

    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
