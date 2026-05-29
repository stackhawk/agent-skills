#!/usr/bin/env python3
"""Back-compat shim. The eval logic now lives in evals/cli.py and evals/lib/.
Run `uv run evals --harness agy --skill <skill>` instead.
This shim forwards old invocations to the new CLI."""
import sys
from evals.cli import main

if __name__ == "__main__":
    if "--harness" not in sys.argv:
        sys.argv += ["--harness", "agy"]
    main()
