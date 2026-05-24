#!/usr/bin/env python3
"""
Cursor manual eval harness for StackHawk agent skills.

Walks through each test prompt interactively. You run the prompt in Cursor
and record what the agent did. Results are saved in the standard format so
they can be compared across platforms.

Usage:
    python3 run-evals.py --skill hawkscan
    python3 run-evals.py --skill api
    python3 run-evals.py --skill hawkscan --id hw-07
    python3 run-evals.py --skill hawkscan --rubric

Requirements:
    - Cursor IDE installed
    - The agent-skills repo open in Cursor
    - Cursor rules auto-applied from cursor/.cursor/rules/ (generated .mdc files)

Note: A headless Cursor CLI (cursor-agent --headless) may exist — see README.md
for investigation status. Until verified, this harness is interactive only.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from _manual_harness import run_manual_evals  # noqa: E402

SETUP_INSTRUCTIONS = """
Setup checklist before starting:
  1. Open Cursor with the agent-skills repo as the workspace root
  2. Cursor rules are in cursor/.cursor/rules/ — confirm they load (Settings → Rules)
  3. Open a Cursor Agent chat (Ctrl+L / Cmd+L, switch to Agent mode)
  4. Have a test project or empty folder ready alongside the repo if needed
  5. Skill behavior is driven by the generated .mdc rules in cursor/.cursor/rules/

For each prompt: paste it into Cursor Agent chat and watch what happens.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cursor manual eval harness for StackHawk skills",
    )
    parser.add_argument("--skill",  required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id",     dest="prompt_id", metavar="RUN_ID")
    parser.add_argument("--rubric", action="store_true",
                        help="Also walk through qualitative rubric checks")
    args = parser.parse_args()

    run_manual_evals(
        platform="cursor",
        setup_instructions=SETUP_INSTRUCTIONS,
        skill=args.skill,
        prompt_id=args.prompt_id,
        rubric=args.rubric,
    )


if __name__ == "__main__":
    main()
