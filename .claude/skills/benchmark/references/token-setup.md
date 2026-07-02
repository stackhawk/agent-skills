# Token Setup

The harness runs `claude` headlessly (no interactive login prompt is
possible inside a cell), so credentials must already be in the environment
before `scripts/run.sh` starts. This covers both the benchmarked-agent
invocation and the skill-blind judge invocation in `grade.py` — both are
plain `claude` CLI calls and both authenticate the same way.

## Option 1 — OAuth token (recommended for interactive/local use)

```bash
claude setup-token
```

This walks through a one-time browser login and prints a token. Export it
in the same shell you'll run the benchmark from:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="<token from setup-token>"
```

## Option 2 — API key

```bash
export ANTHROPIC_API_KEY="<key>"
```

Either variable is sufficient; the `claude` CLI picks up whichever is set.
You do not need both.

## The "source an env file, then run in the same shell" pattern

If you keep tokens in a local, gitignored env file rather than re-exporting
them every session, source it and run the benchmark in the same shell
invocation — exporting in a subshell or a separate `bash -c` won't persist
to the process that runs `run.sh`:

```bash
source ~/.config/agent-skills/benchmark.env   # sets CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY
OLD_REF=... NEW_REF=... BENCH_DIR=... scripts/run.sh
```

Do not put real tokens in `apps.tsv`, `prompt.txt`, or anything under
`ground-truth/` — those paths are exactly what the guard's eval-integrity
check blocks the benchmarked agent from reading (see Step 3 in SKILL.md and
`references/designing-a-harness.md`), but they are still plain files on
disk to anything else running on the machine, so keep secrets in env vars,
not benchmark inputs.

## The token gate behavior

Step 4 of the SKILL.md workflow requires checking for a token *before*
doing any repo/prompt authoring work:

```bash
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || [ -n "$ANTHROPIC_API_KEY" ] || echo "MISSING"
```

If neither is set, stop immediately and tell the user which of the two
options above to run — don't spend time picking repos or writing a prompt
first, since the run will fail at the very first `claude` invocation
regardless of how well-designed the rest of the benchmark is. This is a
hard gate, not a warning: no cell can execute without one of these two
credentials present in the shell that calls `scripts/run.sh`.

## Credentials for the benchmarked task itself (`CRED_ENV`)

The token above authenticates the `claude` CLI process. It is separate from
any credentials the *task* being benchmarked needs (e.g. a `HAWK_API_KEY`
for a task-completion benchmark that re-scans with HawkScan — see the
vuln-remediation example in `references/designing-a-harness.md`). Those are
passed through per-cell via the `CRED_ENV` env var (space-separated
variable names) that `scripts/run.sh` reads and forwards into each cell's
`env`, listed in Step 7 of SKILL.md. Set both independently: the CLI token
in your shell before invoking `run.sh`, and `CRED_ENV`/the named vars it
points to for whatever the task itself needs.
