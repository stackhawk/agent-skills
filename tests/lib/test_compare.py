# tests/lib/test_compare.py
from evals.lib.models import ParsedRun, Verdict
from evals.lib import compare as compare_mod


# A realistic skill-loaded hawkscan run: preflight + step1 discovery + config
# validation + synchronous scan, with output mentioning the app is reachable.
# This satisfies hawkscan's blocking process-checks, the way a real run would.
_WITH_SKILL = ParsedRun(
    bash_commands=[
        "hawk version",
        "hawk config --help",
        "hawkop app list",
        "hawkop env list",
        "hawk init",
        "hawk validate config stackhawk.yml",
        "hawk scan --env Development",
    ],
    output_text="The application was running and reachable on localhost:8080.",
    cost_usd=0.05,
)
_WITHOUT_SKILL = ParsedRun(bash_commands=["echo idk"], cost_usd=0.02)


class StubAdapter:
    platform = "stub"
    def cli_signals(self, skill): return ["hawk scan"]
    def invocation_signals(self, skill): return []
    def parse_stream(self, raw): return ParsedRun()
    def detect_trigger(self, run, skill):
        return any("hawk scan" in c for c in run.bash_commands)
    def launch(self, prompt, skill, run_id, plugin_dirs, *, model, load_skill,
               max_budget, bare, full_auto):
        return _WITH_SKILL if load_skill else _WITHOUT_SKILL


def test_compare_shows_lift(monkeypatch):
    monkeypatch.setattr(compare_mod, "get_adapter", lambda p: StubAdapter())
    rows = compare_mod.compare_skill("hawkscan", "stub", only_id="hw-01")
    row = rows[0]
    assert row["without_verdict"] == Verdict.FAIL          # no skill -> blocking checks fail
    assert row["with_verdict"] in (Verdict.PASS, Verdict.PASS_SLOW)  # skill -> workflow satisfied
    assert row["with_cost"] == 0.05 and row["without_cost"] == 0.02
