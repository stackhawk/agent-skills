# Benchmark Methodology

The invariants that make a benchmark run under this skill trustworthy, and
the reasoning behind the grading approach.

## The invariants

**2-arm.** Every benchmark compares exactly two things: OLD (the skill
before the change) and NEW (the skill after). Both arms run the identical
prompt against the identical repo at the identical pin. The only variable
that differs between an `old__app` cell and a `new__app` cell is which
skill snapshot was materialized into `CLAUDE_CONFIG_DIR/skills`. If more
than one thing differs between the arms, the result can't be attributed to
the change under test.

**3-repo.** Every benchmark exercises 3 real, blindly-cloned repos (see Step
5 in SKILL.md), not one. A single repo's result can be an artifact of that
codebase's quirks; three repos, chosen for variety, catch that. Three is a
floor, not a target — it's small enough to run by hand in one sitting and
large enough that "it worked on all three" or "it regressed on one of
three" is meaningful signal rather than a coin flip.

**Isolation.** Each `arm__app` cell gets its own fresh clone, its own
`CLAUDE_CONFIG_DIR` (built by `harness.sh`'s `build_config_dir`), and its
own guard process bound to that cell's `workdir`. Nothing leaks between
cells except the two read-only skill snapshots under `.skills/old` and
`.skills/new`, which are materialized once per run via `git archive` (see
`materialize_skill` in `harness.sh`) and never written to during execution.

**Ground truth.** Every repo in `apps.tsv` has a corresponding
`ground-truth/<app>.json` — an author-judged, evidence-cited answer key
written *before* looking at what either arm produces. Ground truth is what
the deterministic checks and the judge both grade against; without it,
"exploratory_score" and "correctness" have nothing to be scored relative to.

**Honest verdict.** The report states what happened, not what was hoped
for. That means naming the n=3/1-run limitation every time (see Step 8 in
SKILL.md), and it means the next rule:

## Why hybrid grading (deterministic backbone + skill-blind judge)

Grading happens in two stages, and they are not interchangeable:

1. **Stage 1 — deterministic process-checks.** Regex/parse-based signals
   over the transcript: did the agent read docs, in what order, how many
   distinct files, did it stay within the guard's constraints. These are
   objective, reproducible, and require no model call. They are the
   *evidence backbone* — if the deterministic checks and the judge
   disagree, trust the deterministic checks first.
2. **Stage 2 — skill-blind judge.** An LLM (`JUDGE_MODEL`, invoked with a
   bare `CLAUDE_CONFIG_DIR` and no skills/MCP servers of its own) scores
   correctness against ground truth and flags qualitative failure modes
   (pigeonholing, weak close-rate) that a regex can't capture. The judge
   never sees which arm (old/new) produced the transcript it's grading —
   "skill-blind" means it has no skills loaded, so it can't be biased by
   knowing this skill exists, and it grades the OLD and NEW transcripts by
   the same rubric with no arm label in the prompt.

Neither stage alone is sufficient: deterministic checks can't judge
semantic correctness ("is this the right host?"), and an LLM judge alone is
noisy and non-reproducible at n=1. Combining them means the report can say
"the process-check backbone shows X (reproducible), and the judge's
directional read is Y (treat as corroborating, not primary)."

## Non-discriminating signals are still results

If a signal shows no difference between OLD and NEW — the rates are equal,
or both arms hit 100% / 0% — that is not a failed benchmark. It is a valid
finding: either the change didn't affect that dimension, or the signal
isn't sensitive enough to detect a real difference. Report it as such in
`report.md` rather than omitting it or searching for a way to make the
numbers look more decisive. The app-discovery worked example's `correctness
(judge)` row (4.67/5 OLD vs 4.33/5 NEW — a tie within judge noise at n=1) is
exactly this: it's reported plainly as "tied," not spun.

The one thing this rule does *not* excuse: if the metric the hypothesis was
specifically about fails to move, say that plainly in the Step 8 verdict —
"the hypothesis is not supported by this run" is itself the honest verdict.
