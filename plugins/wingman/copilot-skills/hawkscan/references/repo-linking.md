# Repo Linking (Attack Surface Management)

Linking a StackHawk application to its source repository enables API Discovery
tracking and SCM-driven automapping. Do this once during app onboarding (Phase 0).

## Contents
- [When to Run](#when-to-run)
- [Commands](#commands)
- [How to Identify the Repo](#how-to-identify-the-repo)
- [No Match Fallback: git_origin Tag](#no-match-fallback-git_origin-tag)
- [Full Phase 0a Algorithm](#full-phase-0a-algorithm)
- [hawk op repo list Output Shape](#hawk-op-repo-list-output-shape)

---

## When to Run

- `stackhawk.yml` was just created (new application onboarding)
- The user explicitly requests setup or verification
- NOT on every scan — this is app-level setup

## Commands

```bash
# List all repositories in the org's attack surface
hawk op repo list --format json

# Link an existing app to a repo (additive — safe to re-run)
hawk op repo link --repo-id <REPO_UUID> --app-id <APP_UUID>

# Link by app name (creates a new app if the name doesn't exist)
hawk op repo link --repo-id <REPO_UUID> --app-name "my-api"
```

> ⚠️ **Do not use `--app-name` to create applications.** Application creation must
> go through SKILL.md Step 1 substep 5 (`hawk create app`), which announces the
> settings URL and records the `applicationId`. Use `--app-id` with an
> already-resolved UUID instead.

```bash
# Full replacement (destructive — overwrites all existing app mappings for this repo)
# Use only if you need to remove a previously linked app
hawk op repo set-apps --repo-id <REPO_UUID> --app-ids <UUID1>,<UUID2>
```

**Prefer `repo link` over `repo set-apps`.** The `link` command reads the current
mappings, merges in the new app, and posts the complete list — existing links are
preserved. `set-apps` replaces the entire list.

## How to Identify the Repo

1. Get the git remote URL:
   ```bash
   git remote get-url origin
   ```

2. Normalize both the local URL and every `url` field in `hawk op repo list` output
   using these 4 steps:
   1. Lowercase
   2. Strip `.git` suffix
   3. Strip trailing `/`
   4. Strip protocol+host prefix to obtain the bare `owner/repo` path:
      - HTTPS: strip `https://github.com/` (or equivalent host prefix)
      - SSH SCP-like form (`git@host:path`): strip everything up to and including `:`
      - SSH URL form (`ssh://git@github.com/org/repo`): strip the entire `ssh://git@host/` prefix (everything through the first `/` after the host)
      - Embedded credentials (`https://token@github.com/org/repo`): strip
        credentials before stripping the host (i.e. treat as plain HTTPS)
      - The result is just `org/repo`

3. Match on normalized equality (compare the bare `owner/repo` paths).

### Example

Local: `git@github.com:Org/My-Repo.git`

| Step | Value |
|------|-------|
| 1. Lowercase | `git@github.com:org/my-repo.git` |
| 2. Strip `.git` | `git@github.com:org/my-repo` |
| 3. Strip trailing `/` | `git@github.com:org/my-repo` |
| 4. Strip host (`git@github.com:`) | `org/my-repo` |

API entry `url`: `https://github.com/Org/My-Repo`

| Step | Value |
|------|-------|
| 1. Lowercase | `https://github.com/org/my-repo` |
| 2. Strip `.git` | `https://github.com/org/my-repo` |
| 3. Strip trailing `/` | `https://github.com/org/my-repo` |
| 4. Strip host (`https://github.com/`) | `org/my-repo` |

Both normalize to `org/my-repo` — they match.

## No Match Fallback: `git_origin` Tag

If no repo in the org's attack surface matches the local git remote, do NOT fail —
inject a `git_origin` tag into `stackhawk.yml` instead:

```yaml
tags:
  - name: git_origin
    value: org/my-repo   # bare path after 4-step normalization
```

Use the bare `owner/repo` path (step 4 of normalization) so the platform can match
against any transport. This breadcrumb is visible in every scan from this config.
Once the SCM org is connected in StackHawk's attack surface, the platform can
automap repos to apps using the `git_origin` tag values.

### Full Phase 0a Algorithm

```
1. git remote get-url origin → LOCAL_URL
   If this command fails (no git repo or no origin remote), skip Phase 0a entirely
   and continue to Phase 0b. Repo linking is non-blocking.
2. Apply 4-step normalization to LOCAL_URL → PATH_LOCAL (bare owner/repo path)
3. hawk op repo list --format json → REPOS[]
4. For each repo in REPOS[]:
     apply 4-step normalization to repo.url → PATH_REPO
     if PATH_LOCAL == PATH_REPO:
       hawk op repo link --repo-id repo.id --app-id <APP_ID>
         (where <APP_ID> is the applicationId resolved in SKILL.md Step 1 substep 5)
       Report: "Ensured link: app <APP_NAME> ↔ ASM repo <REPO_NAME>"
       DONE
5. No match found:
   Inject into stackhawk.yml tags block:
     - name: git_origin
       value: PATH_LOCAL
   Report: "No ASM repo match for PATH_LOCAL — added git_origin tag for future automapping"
```

## `hawk op repo list` Output Shape

```json
{
  "data": [
    {
      "id": "uuid",
      "name": "My-Repo",
      "url": "https://github.com/Org/My-Repo",
      "defaultBranch": "main",
      "frameworkNames": ["Spring Boot", "React"],
      "appInfos": [
        { "appId": "uuid", "appName": "my-api" }
      ]
    }
  ]
}
```

`frameworkNames` is a bonus signal — if the repo is already known to StackHawk's
ASM scan, it can inform tech flag detection (Phase 0c) even before inspecting
the local codebase.
