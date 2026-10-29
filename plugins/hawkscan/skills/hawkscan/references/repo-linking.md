# Repo Linking (Attack Surface Management)

Linking a StackHawk application to its source repository enables API Discovery
tracking. Do this once during app onboarding (Phase 0). Linking is best-effort:
it never blocks the scan.

## Contents
- [When to Run](#when-to-run)
- [Hard Rule: Never List to Search](#hard-rule-never-list-to-search)
- [Commands](#commands)
- [Full Phase 0a Algorithm](#full-phase-0a-algorithm)
- [Optional Breadcrumb: git_origin Tag](#optional-breadcrumb-git_origin-tag)

---

## When to Run

- `stackhawk.yml` was just created (new application onboarding)
- The user explicitly requests setup or verification
- NOT on every scan — this is app-level setup

## Hard Rule: Never List to Search

**While linking, never run `hawk op repo list` or `hawk op app list` to find the
repo or app by scanning the output.** The app ID is already known from SKILL.md
Step 1 substep 5. `repo list` pages through every repo in the org (tens of
thousands in large orgs; it can run for many minutes), and its rows carry no repo
ID or remote URL to match on anyway. Let `hawk op repo link --repo <name>` resolve
the name. When `repo link` fails it prints `→ hawkop repo list`; do not follow
that hint.

## Commands

```bash
# Link an existing app to a repo by its bare name (additive — preserves existing links)
hawk op repo link --repo <BARE_NAME> --app-id <APP_UUID>

# Link by repo UUID, only when the user supplied one
hawk op repo link --repo-id <REPO_UUID> --app-id <APP_UUID>
```

`--repo` takes the **bare** repo name (e.g. `my-repo`), not `owner/repo` and not a
URL: those forms return "No repository found". Add `--dry-run` to preview.

> ⚠️ **Do not use `--app-name` to create applications.** Application creation must
> go through SKILL.md Step 1 substep 5 (`hawk create app`), which announces the
> settings URL and records the `applicationId`. Use `--app-id` with an
> already-resolved UUID instead.

```bash
# Full replacement (destructive — overwrites all existing app mappings for this repo)
# Use only if you need to remove a previously linked app
hawk op repo set-apps --repo-id <REPO_UUID> --app-ids <UUID1>,<UUID2>
```

**Prefer `repo link` over `repo set-apps`.** `link` merges the new app into the
repo's existing mappings; `set-apps` replaces the entire list.

## Full Phase 0a Algorithm

```
1. git remote get-url origin → LOCAL_URL
   If this fails (no git repo or no origin remote), skip Phase 0a and continue
   to Phase 0b.
2. BARE_NAME = last path segment of LOCAL_URL, trailing "/" and ".git" stripped
   (e.g. git@github.com:Org/My-Repo.git → My-Repo)
3. Run ONCE, time-boxed to 60 s:
     timeout 60 hawk op repo link --repo <BARE_NAME> --app-id <APP_ID>
   (<APP_ID> is the applicationId from SKILL.md Step 1 substep 5. Without
   `timeout`, e.g. stock macOS: perl -e 'alarm 60; exec @ARGV' hawk op repo link …,
   or your tool's own 60 s command timeout.)
4. Exit 0 → Report: "Linked app <APP_NAME> to repo <BARE_NAME>"
   "No repository found" → Report: "Repo <BARE_NAME> isn't in StackHawk's attack
     surface yet (connect or sync the SCM org) — skipped linking"
   Timeout or any other error → Report: "Repo linking skipped: <reason>"
5. Continue to Phase 0b. Do not retry, list repos, or trigger an SCM sync.
```

## Optional Breadcrumb: `git_origin` Tag

Whether or not the link succeeded, you may add a `git_origin` tag to
`stackhawk.yml`. It records the source repo on every scan from this config, so a
person can see where the scan came from. It does **not** link the app to the
repo; StackHawk does not automap from it.

```yaml
tags:
  - name: git_origin
    value: org/my-repo   # owner/repo path from the git remote, lowercased
```
