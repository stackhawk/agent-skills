#!/usr/bin/env python3
"""
GitHub Copilot manual eval harness for StackHawk agent skills.

Walks through each test prompt interactively. You run the prompt in Copilot
and record what the agent did. Results are saved in the standard format so
they can be compared across platforms.

Usage:
    python3 run-evals.py --skill hawkscan
    python3 run-evals.py --skill api
    python3 run-evals.py --skill hawkscan --id hw-07
    python3 run-evals.py --skill hawkscan --rubric

Requirements:
    - VS Code with GitHub Copilot extension (agent mode enabled)
    - The agent-skills repo open in VS Code
    - Skills discoverable via skills/ symlinks in the repo root
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from _manual_harness import run_manual_evals  # noqa: E402

SETUP_INSTRUCTIONS = """
Setup checklist before starting:
  1. Open VS Code with the agent-skills repo as the workspace root
  2. Ensure the GitHub Copilot extension is installed and agent mode is enabled
  3. Open Copilot Chat (Ctrl+Shift+I / Cmd+Shift+I) in Agent mode (@workspace)
  4. Have a second test project or empty folder ready if the prompt needs one
  5. Skills are auto-discovered from the skills/ directory at the repo root

For each prompt: paste it into Copilot Chat in agent mode and watch what happens.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GitHub Copilot manual eval harness for StackHawk skills",
    )
    parser.add_argument("--skill",  required=True, choices=["hawkscan", "api"])
    parser.add_argument("--id",     dest="prompt_id", metavar="RUN_ID")
    parser.add_argument("--rubric", action="store_true",
                        help="Also walk through qualitative rubric checks")
    args = parser.parse_args()

    run_manual_evals(
        platform="copilot",
        setup_instructions=SETUP_INSTRUCTIONS,
        skill=args.skill,
        prompt_id=args.prompt_id,
        rubric=args.rubric,
    )


if __name__ == "__main__":
    main()
