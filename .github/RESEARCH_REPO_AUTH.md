# Wiring `stackhawk-research` clone auth into the eval CI action

**Goal:** let the hawkscan app-discovery eval cells clone their target repos from the
**`stackhawk-research`** org during a `skill-evals.yml` run, using a **GitHub App** installation
token instead of a personal PAT.

**Why a GitHub App (not a fine-grained PAT):** the App is org-owned (no dependency on one
person's account), mints **short-lived** tokens (~1h) **per workflow run**, is read-only
(`contents:read`), and the token is auto-revoked when the job ends. A PAT would expire, be tied to
a user, and need manual rotation.

**Key fact that makes this cheap:** the claude-code adapter clones with a plain
`git clone https://github.com/stackhawk-research/<repo>.git` (`evals/harnesses/claude-code/adapter.py:138`),
then `git fetch origin <pin>` + `git checkout <pin>`. Git applies an `insteadOf` URL rewrite on
**every** transport operation, so a workflow-level `git config --global url.<token@…>.insteadOf`
authenticates both the clone and the pin fetch **with zero adapter code change.**

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

Two steps run after checkout and before the `Run … evals` step:

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

      - name: Authenticate git for stackhawk-research clones
        if: steps.research-token.outputs.token != ''
        env:
          GH_APP_TOKEN: ${{ steps.research-token.outputs.token }}
        run: |
          git config --global \
            url."https://x-access-token:${GH_APP_TOKEN}@github.com/stackhawk-research/".insteadOf \
            "https://github.com/stackhawk-research/"
```

Notes:
- `create-github-app-token` **masks** the token in logs and **revokes** it in a post-job step. Do
  not `echo` `$GH_APP_TOKEN`.
- No change to `adapter.py`. The `insteadOf` prefix matches every `stackhawk-research` `.git` URL
  and is re-applied on the pin `fetch`, so both authenticate.
- The `if:` guard means when the secrets are missing (e.g. a fork PR) the rewrite step is skipped
  and behavior is identical to today — the discovery cells fall back to plumbing-failed "go
  investigate" signals while the rest of the hawkscan suite still runs.

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
