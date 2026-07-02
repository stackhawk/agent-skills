"""End-to-end integration test for run.sh, with a stub `claude` on PATH.

Unit tests cover the Python logic (guard/grade/report). This test covers the
part that actually broke in practice — the bash orchestration: that a real run
uses cwd = the cloned workdir (so the agent can't see the answer key), that a
guard denial in the stdout transcript flows into stayed_read_only=false, that a
failing cell is isolated without aborting the run, and that grade + report run
end to end and produce report.md.

Fully hermetic: no network (local git clones), no live model (stub `claude`),
no real skill refs (a throwaway agent-skills repo is built here).
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent          # .../skills/benchmark
RUN_SH = ROOT / "scripts" / "run.sh"
MATERIALIZE_DIR = ROOT / ".skills"                             # run.sh writes here (gitignored)

STUB_CLAUDE = r"""#!/usr/bin/env bash
# Stub `claude`. Agent call (--output-format stream-json): record cwd + emit a
# canned transcript containing a doc read, a guard-denied tool_result, and a
# final DISCOVERY block. Judge call (--output-format text): emit a JSON verdict.
mode=""
for a in "$@"; do
  case "$a" in stream-json) mode=agent;; text) mode=judge;; esac
done
if [ "$mode" = judge ]; then
  cat >/dev/null 2>&1 || true   # consume the prompt on stdin
  printf '%s\n' '{"correctness":{"run_command":"correct","host":"correct","api_style":"correct","spa":"correct","auth":"correct"},"exploratory_score":3,"pigeonholed":false}'
  exit 0
fi
# agent mode — cwd MUST be the cloned workdir; record it so the test can assert
printf 'STUB_CWD=%s\n' "$(pwd)" > .stub-ran-here
printf '%s\n' \
 '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"README.md"}}]}}' \
 '{"type":"user","message":{"content":[{"type":"tool_result","is_error":true,"content":"Denied (benchmark guard): Write blocked in readonly profile"}]}}' \
 '{"type":"result","subtype":"success","result":"DISCOVERY:\nrun_command: make run\nhost: http://localhost:8080\napi_style: REST\nspa: no\nauth: required — session cookie"}'
exit 0
"""

GT = {
    "app": "goodapp",
    "run_command": "make run",
    "host": "http://localhost:8080",
    "api_style": "REST",
    "spa": "no",
    "auth": "required — session cookie",
    "evidence": {"run_command": "Makefile", "host": "config", "api_style": "routes",
                 "spa": "templates", "auth": "middleware"},
}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "needs git + bash")
class TestRunShIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bench-it-"))

        # 1) Throwaway "agent-skills" repo so materialize_skill has real refs to archive.
        askills = cls.tmp / "agent-skills"
        subpath = askills / "plugins" / "hawkscan" / "skills" / "hawkscan"
        subpath.mkdir(parents=True)
        (subpath / "SKILL.md").write_text("# fake skill\nStep 1a: Profile the Application\n")
        _git(askills, "init", "-b", "main")
        _git(askills, "add", "-A"); _git(askills, "commit", "-m", "old")
        cls.old_ref = subprocess.check_output(["git", "-C", str(askills), "rev-parse", "HEAD"]).decode().strip()
        (subpath / "SKILL.md").write_text("# fake skill\nStep 1a: Understand the Application\n")
        _git(askills, "add", "-A"); _git(askills, "commit", "-m", "new")
        cls.new_ref = "main"

        # 2) Local "app" repo so `git clone` is offline (branch main, one commit).
        app = cls.tmp / "goodapp-src"
        app.mkdir()
        (app / "README.md").write_text("# goodapp\nrun with make run on :8080\n")
        _git(app, "init", "-b", "main")
        _git(app, "add", "-A"); _git(app, "commit", "-m", "init")

        # 3) BENCH_DIR: apps.tsv (a good local app + a bad one for isolation), prompt, ground truth.
        bench = cls.tmp / "bench"
        (bench / "ground-truth").mkdir(parents=True)
        (bench / "apps.tsv").write_text(
            f"goodapp\t{app}\tmain\n"
            f"badapp\t{cls.tmp}/does-not-exist\tmain\n"
        )
        (bench / "prompt.txt").write_text("Discover the app. End with a DISCOVERY: block.\n")
        (bench / "ground-truth" / "goodapp.json").write_text(json.dumps(GT))
        cls.bench = bench

        # 4) Stub `claude` on PATH.
        binp = cls.tmp / "bin"; binp.mkdir()
        stub = binp / "claude"; stub.write_text(STUB_CLAUDE); stub.chmod(0o755)

        # 5) Run the REAL run.sh end to end.
        env = {**os.environ,
               "PATH": f"{binp}{os.pathsep}{os.environ['PATH']}",
               "AGENT_SKILLS_REPO": str(askills),
               "SKILL_SUBPATH": "plugins/hawkscan/skills/hawkscan",
               "OLD_REF": cls.old_ref, "NEW_REF": cls.new_ref,
               "BENCH_DIR": str(bench),
               "PROFILE": "readonly", "GRADER": "observational",
               "MODEL": "stub-model", "JUDGE_MODEL": "stub-judge"}
        cls.proc = subprocess.run(["bash", str(RUN_SH)], env=env,
                                  capture_output=True, text=True)
        runs = sorted((bench / "runs").glob("*"))
        cls.run_dir = runs[-1] if runs else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(MATERIALIZE_DIR, ignore_errors=True)  # run.sh writes .skills/ into the skill dir

    def test_run_completed_and_reported(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIsNotNone(self.run_dir, "no runs/<ts> dir created")
        report = self.run_dir / "report.md"
        self.assertTrue(report.exists(), "report.md not produced")
        self.assertIn("goodapp", report.read_text())

    def test_both_arms_ran_for_good_app(self):
        for arm in ("old", "new"):
            cell = self.run_dir / "cells" / f"{arm}__goodapp"
            self.assertTrue((cell / "checks.json").exists(), f"{arm}: no checks.json")
            self.assertTrue((cell / "grade.json").exists(), f"{arm}: no grade.json (judge)")

    def test_cwd_was_the_cloned_workdir(self):
        # the anti-contamination fix: the agent runs with cwd = the cloned app,
        # not the harness/BENCH_DIR (where ground-truth lives).
        for arm in ("old", "new"):
            cell = self.run_dir / "cells" / f"{arm}__goodapp"
            marker = cell / "workdir" / ".stub-ran-here"
            self.assertTrue(marker.exists(), f"{arm}: stub didn't run in workdir")
            recorded = marker.read_text().strip().split("=", 1)[1]
            self.assertEqual(os.path.realpath(recorded),
                             os.path.realpath(cell / "workdir"),
                             f"{arm}: cwd was not the workdir")

    def test_guard_denial_flows_into_stayed_read_only(self):
        # guard denial appears in the stdout transcript -> guard-denies.txt ->
        # grade.py sets stayed_read_only=False. This is the wrong-stream bug's regression.
        for arm in ("old", "new"):
            cell = self.run_dir / "cells" / f"{arm}__goodapp"
            self.assertTrue((cell / "guard-denies.txt").stat().st_size > 0,
                            f"{arm}: guard denial not captured from transcript")
            checks = json.loads((cell / "checks.json").read_text())
            self.assertFalse(checks["stayed_read_only"], f"{arm}: stayed_read_only should be False")
            self.assertTrue(checks["read_agent_docs"], f"{arm}: README read should register")

    def test_failing_cell_is_isolated(self):
        # badapp's clone fails; it must not abort the run, and the good app still graded.
        for arm in ("old", "new"):
            bad = self.run_dir / "cells" / f"{arm}__badapp"
            self.assertTrue((bad / "error").exists(), f"{arm}: badapp should have an error sentinel")
            self.assertFalse((bad / "grade.json").exists(), f"{arm}: badapp should not have been graded")


if __name__ == "__main__":
    unittest.main()
