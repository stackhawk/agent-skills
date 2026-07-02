# Gotchas

Durable lessons this harness has already learned the hard way. Skim this
before running and again before writing the Step 8 verdict.

## Contents
- [The 5 durable lessons](#the-5-durable-lessons)
  - [1. cwd must be the cloned workdir, never this repo](#1-cwd-must-be-the-cloned-workdir-never-this-repo)
  - [2. Guard denials must be captured from the transcript, not assumed](#2-guard-denials-must-be-captured-from-the-transcript-not-assumed)
  - [3. Headless flags are load-bearing, not boilerplate](#3-headless-flags-are-load-bearing-not-boilerplate)
  - [4. Per-cell isolation is what makes the comparison valid, not incidental](#4-per-cell-isolation-is-what-makes-the-comparison-valid-not-incidental)
  - [5. A non-discriminating signal is still an honest result](#5-a-non-discriminating-signal-is-still-an-honest-result)
- [The guard is a safety net, not an adversarial boundary](#the-guard-is-a-safety-net-not-an-adversarial-boundary)

---

## The 5 durable lessons

### 1. cwd must be the cloned workdir, never this repo

`run.sh` invokes `claude` with `cd "$cell/workdir"` — the benchmarked
agent's working directory is the fresh clone, not `agent-skills`. **Why it
matters:** if the agent's cwd were this repo, every relative path it reads
would resolve inside `agent-skills`, exposing ground truth, the plan, and
the harness scripts it should never see — and the guard's eval-integrity
regex is a second line of defense, not the only one. Get the cwd right and
most of the eval-integrity surface disappears on its own.

### 2. Guard denials must be captured from the transcript, not assumed

`run.sh` greps the actual `transcript.jsonl` and `agent.stderr` for
`Denied (benchmark guard` into `guard-denies.txt`, and `grade.py` only sets
`stayed_read_only = False` if that file is non-empty. **Why it matters:**
it's tempting to reason "the guard is readonly, so of course nothing got
written" — but the only trustworthy evidence that the guard actually fired
(as opposed to the agent simply not trying) is the deny line in the
transcript. Silence in `guard-denies.txt` could mean "guard worked" or
"guard hook wasn't wired up at all" — always check that the hook is
present in the cell's `settings.json` before trusting an empty file as a
pass.

### 3. Headless flags are load-bearing, not boilerplate

`run.sh`'s `claude` invocation uses `--print --verbose --output-format
stream-json --permission-mode bypassPermissions`, plus
`BASH_DEFAULT_TIMEOUT_MS`/`BASH_MAX_TIMEOUT_MS` set generously (45/60 min).
**Why it matters:** `--print` + `stream-json` is what makes the transcript
parseable by `grade.py` at all; `bypassPermissions` is required because
there's no human present in a headless cell to click "allow" — the *guard*
is what enforces boundaries instead, not the interactive permission
prompt. Drop any of these and the run either hangs waiting for approval or
produces an unparseable transcript.

### 4. Per-cell isolation is what makes the comparison valid, not incidental

Each `arm__app` cell gets its own clone, its own `CLAUDE_CONFIG_DIR`
(built fresh by `build_config_dir`), and its own guard process scoped to
its own `--workdir`. **Why it matters:** if two cells shared a
`CLAUDE_CONFIG_DIR` or a clone, a write or cached state from one cell could
leak into the next and contaminate the comparison — you'd be measuring
"whichever arm ran second" instead of "OLD vs NEW." Never reuse a `cell/`
directory across arms or apps, and never point `BENCH_DIR` at a location
that isn't fresh per run (`run.sh` already timestamps `runs/<TS>/` for
this reason).

### 5. A non-discriminating signal is still an honest result

If a check comes back equal across arms, or the judge scores a tie, that
is data — not a harness failure to paper over by re-running until you get
a more flattering split. **Why it matters:** the entire point of the
n=3/1-run caveat (see `references/methodology.md`) is that this harness
gives directional evidence, and directional evidence sometimes points
nowhere. Report ties and misses in `report.md`'s verdict exactly as
plainly as you'd report a win — see Step 8 in SKILL.md.

---

## The guard is a safety net, not an adversarial boundary

`scripts/guard.py` does three jobs: it enforces **eval integrity** (blocks
reads of ground-truth, `.superpowers`, `apps.tsv`, `prompt.txt`, and the
benchmark scripts themselves), it enforces **real-world safety** (no `git
push`/`git remote`, no network egress to a non-local host), and it applies
a **permission profile** (`readonly` vs `sandbox-rw`, see
`references/designing-a-harness.md`).

All three of those checks are pattern-matching heuristics over tool names
and string targets — not a sandboxed execution environment, a network
namespace, or a filesystem jail. A **determined adversary** could bypass
them: shell indirection (`$(echo Y3VybA== | base64 -d)`... to reconstruct a
blocked command, writing a script file and executing it instead of calling
the write tool directly, obfuscating a host as a raw IP or hex-encoded
string to slip past the hostname regex, etc. None of that is hardened
against here.

That gap is an **accepted residual risk**, not an oversight, for one
reason: the agent under benchmark is **cooperative**. It's this same
`benchmark` skill running a benign discovery/remediation task against a
cloned OSS repo, in a local, offline cell, with no adversarial incentive to
escape the guard. The real isolation this harness relies on isn't the
guard's regexes — it's structural: **cwd is the cloned app** (gotcha #1
above), **ground truth lives outside that cwd and outside the agent's
reach**, and **there is no network path out of the cell that the guard's
egress check needs to catch anything sophisticated to stop**, because nothing
in a cooperative run is trying to reach the network in the first place.

**Do not** point this harness at an untrusted or adversarial agent (e.g. a
third-party skill you don't trust, or a red-team exercise) without first
hardening it — real process/network sandboxing (containers, network
namespaces, seccomp), not just `guard.py`'s pattern matching. Using it that
way today would be trusting a heuristic to hold a boundary it was never
designed to hold.
