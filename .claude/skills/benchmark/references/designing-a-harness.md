# Designing a Harness

How to decide what kind of benchmark you're running, and how that decision
sets every other config knob in `scripts/run.sh`.

## Contents
- [The one decision: observational vs task-completion](#the-one-decision-observational-vs-task-completion)
- [What each guard profile actually allows](#what-each-guard-profile-actually-allows)
- [What the prompt must elicit](#what-the-prompt-must-elicit)
- [Worked example 1 — discovery (observational, readonly)](#worked-example-1--discovery-observational-readonly)
- [Worked example 2 — vulnerability remediation (task-completion, sandbox-rw)](#worked-example-2--vulnerability-remediation-task-completion-sandbox-rw)

---

## The one decision: observational vs task-completion

Ask: **does the hypothesis claim the agent behaves differently, or that the
agent finishes a job differently?**

- **Observational** — the hypothesis is about *process*: does the agent
  read docs first, explore more broadly, avoid a legacy pattern, ask the
  right questions before concluding? Nothing needs to actually run, build,
  or get fixed — you're grading the trajectory, not an artifact.
- **Task-completion** — the hypothesis is about *outcome*: does the agent
  actually close a vulnerability, make a passing test pass, produce a
  correct diff? You need the agent to be able to write files and often run
  commands to attempt the task at all.

This single classification cascades into three settings:

| Setting | Observational | Task-completion |
|---|---|---|
| `PROFILE` | `readonly` | `sandbox-rw` |
| `CRED_ENV` | usually empty | often non-empty (task-specific secrets) |
| `GRADER` | `observational` | `task-completion` |

## What each guard profile actually allows

Both profiles are enforced by `scripts/guard.py`, wired in as a
`PreToolUse` hook via `build_config_dir` in `harness.sh`. Both profiles
*always* enforce eval-integrity (denies any path/pattern matching
ground-truth, `.superpowers`, `apps.tsv`, `prompt.txt`, or the benchmark
scripts themselves) and real-world safety (no `git push`/`git remote`, no
network egress to a non-local host via curl/wget/nc/ssh/scp). On top of
that floor:

- **`readonly`** additionally denies every write tool (`Write`, `Edit`,
  `MultiEdit`, `NotebookEdit`) outright, and denies `Bash` commands that
  write (`rm`, `mv`, `tee`, `dd`, redirects) or start/run/scan something
  (`docker`/`docker compose`, `npm start`/`run dev`/`serve`, `bootRun`,
  `uvicorn`, `hawk scan`, etc. — see `RUN_OR_SCAN` in `guard.py`).
- **`sandbox-rw`** allows writes and run/scan commands, but confines every
  write-tool target to inside `--workdir` (realpath-checked, so a symlink
  or `..` escape is still denied). It does not add its own execution
  sandbox beyond that — it relies on the clone being disposable and the
  eval-integrity/safety rules always being on.

Pick `readonly` whenever the agent doesn't need to change anything to
demonstrate the behavior. Reach for `sandbox-rw` only when the hypothesis
requires the agent to produce a diff or run something.

## What the prompt must elicit

- **Observational prompts** must ask for a structured, parseable
  conclusion block, because Stage 1 grading (see
  `references/grading.md`) is regex-based and needs a fixed shape to
  check against. The app-discovery example's prompt ends with a literal
  `DISCOVERY:` header and five fixed fields
  (`run_command`/`host`/`api_style`/`spa`/`auth`) for exactly this reason.
- **Task-completion prompts** must describe the job with enough
  specificity that "done" is unambiguous, and should explicitly permit the
  agent to run/build/test locally (otherwise a `sandbox-rw` agent may still
  behave conservatively). The grader reads the agent's final message and
  `fix.diff`, not a structured block, so the prompt doesn't need a fixed
  answer format — but it does need to make the success criterion legible
  enough for a judge to score `close_rate` against ground truth.

## Worked example 1 — discovery (observational, `readonly`)

This is `examples/app-discovery/`, the shipped worked example. Hypothesis:
the v2.0.0 → v2.1.0 hawkscan reframe should make agents read repo docs
*before* concluding, rather than jumping straight to a prescriptive
command menu.

- `PROFILE=readonly` — the agent only needs to read and report; nothing it
  does should touch the filesystem or start a service.
- `CRED_ENV` empty — discovery needs no platform credentials.
- `GRADER=observational` — grade the transcript's tool-call trajectory
  (`read_agent_docs`, `docs_before_conclusion`, `explored_manifests`, etc.)
  plus a skill-blind judge's correctness score against
  `ground-truth/<app>.json`.
- Prompt ends in the `DISCOVERY:` block described above.

## Worked example 2 — vulnerability remediation (task-completion, `sandbox-rw`)

Hypothesis: a change to a remediation-guidance skill should raise the
fraction of a known vulnerability set that gets actually fixed, without
breaking the app or quietly reducing scan coverage to hide findings.

- `PROFILE=sandbox-rw` — the agent must edit source files and typically
  needs to run the app or its test suite to verify a fix; `readonly` would
  make the task impossible.
- `CRED_ENV="HAWK_API_KEY"` — remediation verification that involves
  re-scanning with HawkScan needs a StackHawk API key passed through into
  the cell; `run.sh` passes through only the named vars listed in
  `CRED_ENV`, nothing else from the calling shell's environment.
- `GRADER=task-completion` — a skill-blind judge reads the agent's final
  message and `fix.diff` and returns `close_rate` (fraction of the
  expected vulns plausibly fixed), `coverage_not_reduced` (did it avoid
  disabling checks/routes to hide findings), and `app_not_broken`.
- The prompt describes the vulnerable behavior and asks the agent to fix
  it using whatever tools it needs; it does not need a structured answer
  block, since grading reads the diff and final message directly.

For how each grader actually scores its cells, see
`references/grading.md`. For the token/credential mechanics behind
`CRED_ENV`, see Step 4 in SKILL.md and `references/token-setup.md`.
