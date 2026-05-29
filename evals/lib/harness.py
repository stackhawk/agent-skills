"""Harness protocol + adapter registry. An adapter owns everything runtime-specific:
how to launch the agent, how to parse its stream, and which signals indicate the
skill fired. Everything downstream consumes the ParsedRun it returns."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Protocol

from evals.lib.models import ParsedRun

EVALS_DIR = Path(__file__).resolve().parent.parent


class Harness(Protocol):
    platform: str
    def cli_signals(self, skill: str) -> list[str]: ...
    def invocation_signals(self, skill: str) -> list[str]: ...
    def parse_stream(self, raw: str) -> ParsedRun: ...
    def detect_trigger(self, run: ParsedRun, skill: str) -> bool: ...
    def launch(self, prompt: str, skill: str, run_id: str, plugin_dirs: list[str],
               *, model: str | None, load_skill: bool, max_budget: float,
               bare: bool, full_auto: bool) -> ParsedRun: ...


def get_adapter(platform: str) -> Harness:
    path = EVALS_DIR / "harnesses" / platform / "adapter.py"
    if not path.exists():
        raise ValueError(f"no adapter for platform '{platform}' at {path}")
    spec = importlib.util.spec_from_file_location(f"adapter_{platform.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ADAPTER
