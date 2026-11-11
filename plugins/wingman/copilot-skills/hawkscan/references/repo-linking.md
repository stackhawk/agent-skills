# Repo Linking (Attack Surface Management)

Linking a StackHawk application to its source repository enables API Discovery
tracking. Do this once during app onboarding (Phase 0). Linking is best-effort:
it never blocks the scan.

## Contents
- [When to Run](#when-to-run)
- [Commands](#commands)
- [Full Phase 0a Algorithm](#full-phase-0a-algorithm)
- [Optional Breadcrumb: git_origin Tag](#optional-breadcrumb-git_origin-tag)

---

## When to Run

- `stackhawk.yml` was just created (new application onboarding)
- The user explicitly requests setup or verification
- NOT on every scan — this is app-level setup

## Commands

```bash
# Link an existing app to a repo by its bare name (additive — preserves existing links)
hawk op repo link --repo <BARE_NAME> --app-id <APP_UUID>
```

Pass `--repo` the **bare** repo name (e.g. `my-repo`), never `owner/repo` or a
URL: those forms return "No repository found". The app ID is already known from
SKILL.md Step 1 substep 5.

**Never run `hawk op repo list` (or `hawk op app list`) while linking.** It pages
through every repo in the org, which can take many minutes in large orgs. Ignore
any `→ hawkop …` hint that `repo link` prints.

> ⚠️ **Do not use `--app-name` to create applications.** Application creation must
> go through SKILL.md Step 1 substep 5 (`hawk create app`), which announces the
> settings URL and records the `applicationId`. Use `--app-id` with an
> already-resolved UUID instead.

## Full Phase 0a Algorithm

```
1. git remote get-url origin → LOCAL_URL
   If this fails (no git repo or no origin remote), skip Phase 0a and continue
   to Phase 0b.
2. BARE_NAME = last segment of LOCAL_URL after splitting on "/" and ":",
   trailing "/" and ".git" stripped
   (e.g. git@github.com:Org/My-Repo.git → My-Repo; https://github.com/org/api.git → api)
3. Run ONCE, time-boxed to 60 s:
     hawk op repo link --repo <BARE_NAME> --app-id <APP_ID>
   Time box: if `command -v timeout` succeeds, prefix the command with
   `timeout 60`; otherwise (e.g. stock macOS or Windows) run it as-is under
   your tool's own 60 s command timeout. A missing `timeout` binary is not a
   link failure.
4. Exit 0 → Report: "Linked app <APP_NAME> to repo <BARE_NAME>"
   Timeout, non-zero exit, or any error → stop linking and report as status
   output (never a prompt; do not pause the run):
     "Couldn't link app <APP_NAME> to repo <BARE_NAME> automatically
     (<reason>). To link it yourself: in StackHawk, open Attack Surface,
     find the repo <BARE_NAME>, and add the app <APP_NAME> to it."
5. Continue to Phase 0b. Do not retry, list repos, or trigger an SCM sync.
```

## Optional Breadcrumb: `git_origin` Tag

You may add a `git_origin` tag to `stackhawk.yml`. It records the source repo on
every scan from this config, so a person can see where the scan came from. It
does **not** link the app to the repo; StackHawk does not automap from it.

```yaml
tags:
  - name: git_origin
    value: org/my-repo   # owner/repo path from the git remote, lowercased
```
