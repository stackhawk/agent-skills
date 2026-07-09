# Wiring `stackhawk-research` clone auth into the eval CI action

**Goal:** let the hawkscan app-discovery eval cells clone their target repos from the
**`stackhawk-research`** org during a `skill-evals.yml` run, using a **GitHub App** installation
token instead of a personal PAT.

**Why a GitHub App (not a fine-grained PAT):** the App is org-owned (no dependency on one
person's account), mints **short-lived** tokens (~1h) **per workflow run**, is read-only
(`contents:read`), and the token is auto-revoked when the job ends. A PAT would expire, be tied to
a user, and need manual rotation.

**How the token reaches the clone:** the claude-code adapter clones the target
(`git clone` + `git fetch origin <pin>` + `git checkout <pin>`) in
`evals/harnesses/claude-code/adapter.py`. When `RESEARCH_REPO_TOKEN` is set, the adapter embeds it
in the clone URL for its own clone/fetch, then **scrubs it** (drops the remote, pops it from the
agent env, redacts it from errors) before the discovery agent runs — see "Workflow wiring" below.
The token is never written to `~/.gitconfig` or left in `.git/config`.

The two related files in this directory:
- `research-repo-reader-app.manifest.json` — the GitHub App manifest (source of truth for the App's name/permissions).
- `create-research-repo-reader-app.html` — a self-contained runbook an org admin opens to create the App, generate a key, install it, and set the repo secrets (covers "Setup" below).

---

## Setup (one-time, done by an admin of both orgs)

Handled by the `create-research-repo-reader-app.html` runbook. In short:

1. Create the App in `stackhawk-research` from the manifest (permissions `contents:read` +
   `metadata:read`, webhooks off, private).
2. Copy the **App ID**; **generate a private key** (`.pem`).
3. **Install App** on `stackhawk-research` → **All repositories** (read-only, so any future eval
   target works with no re-install).
4. Add two secrets to `stackhawk/agent-skills` (`Settings → Secrets and variables → Actions`):

   | Secret | Value |
   |---|---|
   | `RESEARCH_APP_ID` | the numeric App ID |
   | `RESEARCH_APP_PRIVATE_KEY` | the **full contents** of the `.pem`, including the BEGIN/END lines |

The App lives in `stackhawk-research`, but its App ID + private key are used from the
`agent-skills` workflow — cross-org is exactly what `create-github-app-token` + `owner:` handles.

## Workflow wiring (`.github/workflows/skill-evals.yml`, `eval-claude-code` job)

One step mints the token; it is then handed to the eval as a step-scoped env var. The adapter
(not git's global config) injects it into its own clone/fetch and scrubs it before the agent runs
— so the token is never resident on disk or in the agent's env while the discovery agent explores
under `--dangerously-skip-permissions`.

```yaml
      - name: Mint stackhawk-research read token
        id: research-token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.RESEARCH_APP_ID }}
          private-key: ${{ secrets.RESEARCH_APP_PRIVATE_KEY }}
          owner: stackhawk-research
          # No `repositories:` — the App is installed on ALL stackhawk-research repos
          # (read-only), so the token covers any current or future eval target with no
          # workflow change. Add `repositories: a,b,c` here only to re-scope down.
        continue-on-error: true   # absent secrets must not red the job

      - name: Run <skill> evals ...
        env:
          # ... ANTHROPIC_API_KEY / HAWK_API_KEY ...
          RESEARCH_REPO_TOKEN: ${{ steps.research-token.outputs.token }}
        run: uv run evals --harness claude-code --skill <skill> ...
```

How the adapter uses it (`evals/harnesses/claude-code/adapter.py`, `target_repo` cells only):
1. If `RESEARCH_REPO_TOKEN` is set **and** the target URL is under
   `https://github.com/stackhawk-research/` (the org the token is scoped to), embed it in the
   clone URL for the adapter's own `clone` + pin `fetch`.
2. After checkout, `git remote remove origin` — scrubs the token-bearing URL from `.git/config`.
3. `env.pop("RESEARCH_REPO_TOKEN")` before spawning `claude`, and redact the token from any
   surfaced clone/fetch error. So it is not in `~/.gitconfig`, `.git/config`, or the agent env.

Notes:
- `create-github-app-token` **masks** the token in logs and **revokes** it in a post-job step.
- When the secrets are missing (e.g. a fork PR) `RESEARCH_REPO_TOKEN` is empty, the adapter clones
  anonymously, and the discovery cells fall back to plumbing-failed "go investigate" signals while
  the rest of the hawkscan suite still runs.
- Known follow-up: the token is passed in the adapter's `git clone` argv (visible via `ps` for that
  subprocess's lifetime). Low risk on ephemeral single-tenant GitHub-hosted runners; routing it
  through `GIT_ASKPASS` / a credential helper would remove that last surface.

## Run it (the pre-merge smoke gate for PR #69)

The **run-without-publish** path — it does **not** create a release baseline
(`capture-baseline.yml` + a `tag` input is the publish path; unaffected here):

```bash
gh workflow run skill-evals.yml \
  --ref worktree-evals-discovery \
  -f platform=claude-code -f rubric=true
```

Watch the `claude-code / hawkscan / …` cells. **Success criteria:** the four discovery ids
(`firefly-iii`, `wikijs`, `memos`, `dawarich`) clone, run, and produce a `DISCOVERY:` block that
the answer-key judge grades — no `clone failed:` / `checkout failed:` errors in their traces.
Once green, mark PR #69 ready for review.

---

## Scope caveats / follow-ups (not blocking a smoke run)

- **Other harnesses.** The `hawkscan` matrix cell also runs under `eval-codex`, `eval-agy`,
  `eval-cursor`. Only the **claude-code** adapter implements `target_repo` cloning today, so the
  App-token wiring goes in the claude-code job first. Before enabling discovery on the other
  platforms, (1) implement `target_repo` in those adapters and (2) copy the two steps above into
  their jobs.
- **Pin bumps.** `stackhawk-research` mirrors carry no release tags, so `prompts.yaml` pins to commit
  SHAs. Re-verify the answer keys whenever a pin changes.
- **Expanding the repo set.** The App is installed on **all** `stackhawk-research` repos and the
  minted token is org-wide, so adding a future eval target needs no App or workflow change — just
  add the `target_repo` entry in `prompts.yaml`.
