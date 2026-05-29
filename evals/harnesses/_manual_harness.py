"""
Shared interactive evaluation loop for manual harnesses (Copilot, Cursor).
Import this from platform-specific run-evals.py files.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evals.lib.config import load_skill


HARNESS_ROOT = Path(__file__).parent.resolve()
EVALS_DIR    = HARNESS_ROOT.parent
REPO_ROOT    = EVALS_DIR.parent


def _yn(question: str) -> str:
    """Prompt for y / n / skip. Returns 'y', 'n', or 'skip'."""
    while True:
        raw = input(question).strip().lower()
        if raw in ("y", "yes"):
            return "y"
        if raw in ("n", "no"):
            return "n"
        if raw in ("s", "skip", ""):
            return "skip"
        print("  Enter y, n, or s/skip.")


def run_manual_evals(
    platform: str,
    setup_instructions: str,
    skill: str,
    prompt_id: str | None,
    rubric: bool,
) -> None:
    results_dir  = HARNESS_ROOT / platform / "results" / skill

    cfg = load_skill(skill)
    all_prompts = cfg.prompts
    checks = cfg.checks
    blocking_checks = [c for c in checks if c.get("severity") == "blocking"]

    rubric_items = None
    if rubric:
        # rubric-items.json is not yet part of evals.lib — loaded directly for now
        rubric_path = EVALS_DIR / skill / "rubric-items.json"
        if rubric_path.exists():
            rubric_items = json.loads(rubric_path.read_text())["checks"]

    if prompt_id:
        prompts = [p for p in all_prompts if p.id == prompt_id]
        if not prompts:
            print(f"ERROR: No prompt with id '{prompt_id}'", file=sys.stderr)
            sys.exit(1)
    else:
        prompts = all_prompts

    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'═' * 68}")
    print(f"  Manual Skill Eval  |  skill={skill}  platform={platform}")
    print(f"{'═' * 68}")
    print(setup_instructions)
    input("Press Enter to begin evaluating...\n")

    all_results = []

    for row in prompts:
        run_id         = row.id
        prompt         = row.prompt
        should_trigger = row.should_trigger
        itype          = row.invocation_type
        notes          = row.notes

        print(f"\n{'─' * 68}")
        print(f"[{run_id}]  {itype:<12}  should_trigger={'Y' if should_trigger else 'N'}")
        print(f"\nPrompt:\n  {prompt}\n")
        if notes:
            print(f"Context: {notes}\n")

        input("Run this prompt now, then press Enter to record results...")

        # ── Trigger detection ──────────────────────────────────────────────
        trigger_resp = _yn(
            f"\nDid the {platform} agent invoke the {skill} skill? "
            "(y / n / skip to skip this prompt): "
        )
        if trigger_resp == "skip":
            print("  → skipped")
            continue

        did_trigger = trigger_resp == "y"
        trigger_ok  = did_trigger == should_trigger

        if not trigger_ok:
            expected = "trigger" if should_trigger else "NOT trigger"
            got      = "triggered" if did_trigger else "did not trigger"
            print(f"  ⚠ MISMATCH: expected {expected}, agent {got}")

        # ── Process checks (blocking only, only when skill should fire and did) ──
        process_results: list[dict] = []
        if should_trigger and did_trigger and blocking_checks:
            print(f"\nProcess checks ({len(blocking_checks)} blocking):")
            for i, check in enumerate(blocking_checks, 1):
                print(f"\n  [{i}/{len(blocking_checks)}] {check['id']}")
                print(f"  {check['description']}")
                signals = check.get("signals", [])
                if signals:
                    print(f"  Look for: {', '.join(signals[:4])}")
                antis = check.get("anti_patterns", [])
                if antis:
                    print(f"  Must NOT see: {', '.join(antis[:3])}")

                resp = _yn("  Pass? (y / n / skip): ")
                if resp == "skip":
                    continue
                process_results.append({
                    "id":           check["id"],
                    "pass":         resp == "y",
                    "severity":     "blocking",
                    "signal_found": None,
                    "anti_found":   None,
                })

        # ── Rubric (optional) ─────────────────────────────────────────────
        rubric_result = None
        if rubric and rubric_items and should_trigger and did_trigger:
            print(f"\nRubric checks ({len(rubric_items)} qualitative):")
            rubric_checks_out = []
            for i, check in enumerate(rubric_items, 1):
                print(f"\n  [{i}/{len(rubric_items)}] {check['id']}")
                print(f"  {check['description']}")
                resp = _yn("  Pass? (y / n / skip): ")
                if resp == "skip":
                    continue
                rubric_checks_out.append({
                    "id": check["id"],
                    "pass": resp == "y",
                    "notes": "",
                })

            if rubric_checks_out:
                passed = sum(1 for c in rubric_checks_out if c["pass"])
                score  = int(100 * passed / len(rubric_checks_out))
                rubric_result = {
                    "skill":        skill,
                    "run_id":       run_id,
                    "overall_pass": score >= 70,
                    "score":        score,
                    "checks":       rubric_checks_out,
                }

        # ── Score ──────────────────────────────────────────────────────────
        blocking_failed = sum(1 for r in process_results if not r["pass"])
        score = max(0, 100 - blocking_failed * 15)
        scoring = {
            "total":           len(process_results),
            "passed":          sum(1 for r in process_results if r["pass"]),
            "blocking_failed": blocking_failed,
            "warning_failed":  0,
            "score":           score,
        }

        result = {
            "platform":        platform,
            "skill":           skill,
            "run_id":          run_id,
            "prompt":          prompt,
            "should_trigger":  should_trigger,
            "did_trigger":     did_trigger,
            "trigger_correct": trigger_ok,
            "bash_commands":   [],
            "files_written":   [],
            "process_checks":  process_results,
            "scoring":         scoring,
            "rubric_result":   rubric_result,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }
        all_results.append(result)
        (results_dir / f"{run_id}.result.json").write_text(json.dumps(result, indent=2))

        t_icon    = "✓" if trigger_ok else "✗"
        score_str = f"score={scoring['score']}/100" if process_results else "—"
        print(f"\n  {t_icon} trigger_correct={trigger_ok}  {score_str}")

    if not all_results:
        return

    # ── Final summary ──────────────────────────────────────────────────────
    trigger_correct = sum(1 for r in all_results if r["trigger_correct"])
    total      = len(all_results)
    false_pos  = [r for r in all_results if not r["should_trigger"] and r["did_trigger"]]
    false_neg  = [r for r in all_results if r["should_trigger"] and not r["did_trigger"]]
    proc_runs  = [r for r in all_results if r["process_checks"]]
    avg_score  = (sum(r["scoring"]["score"] for r in proc_runs) // len(proc_runs)
                  if proc_runs else None)
    total_blocking = sum(r["scoring"]["blocking_failed"] for r in proc_runs) if proc_runs else 0

    print(f"\n{'═' * 68}")
    print(f"SUMMARY  skill={skill}  platform={platform}")
    print(f"  Trigger accuracy : {trigger_correct}/{total} ({100 * trigger_correct // total}%)")
    if false_pos:
        print(f"  False positives  : {', '.join(r['run_id'] for r in false_pos)}")
    if false_neg:
        print(f"  False negatives  : {', '.join(r['run_id'] for r in false_neg)}")
    if avg_score is not None:
        print(f"  Process avg score: {avg_score}/100  (blocking failures: {total_blocking})")
    print(f"  Results in       : {results_dir}/")

    summary = {
        "skill":    skill,
        "platform": platform,
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
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
