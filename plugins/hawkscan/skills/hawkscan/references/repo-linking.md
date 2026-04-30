# Repo Linking (Attack Surface Management)

Linking a StackHawk application to its source repository enables API Discovery
tracking and SCM-driven automapping. Do this once during app onboarding (Phase 0).

## When to Run

- `stackhawk.yml` was just created (new application onboarding)
- The user explicitly requests setup or verification
- NOT on every scan — this is app-level setup

## Commands

```bash
# List all repositories in the org's attack surface
hawkop repo list --format json

# Link an existing app to a repo (additive — safe to re-run)
hawkop repo link --repo-id <REPO_UUID> --app-id <APP_UUID>

# Link by app name (creates a new app if the name doesn't exist)
hawkop repo link --repo-id <REPO_UUID> --app-name "my-api"

# Full replacement (destructive — overwrites all existing app mappings for this repo)
# Use only if you need to remove a previously linked app
hawkop repo set-apps --repo-id <REPO_UUID> --app-ids <UUID1>,<UUID2>
```

**Prefer `repo link` over `repo set-apps`.** The `link` command reads the current
mappings, merges in the new app, and posts the complete list — existing links are
preserved. `set-apps` replaces the entire list.

## How to Identify the Repo

1. Get the git remote URL:
   ```bash
   git remote get-url origin
   ```

2. Normalize both the local URL and every `url` field in `hawkop repo list` output:
   - Lowercase
   - Strip `.git` suffix
   - Strip trailing `/`

3. Match on normalized equality.

### Example

Local: `git@github.com:Org/My-Repo.git`
Normalized: `git@github.com:org/my-repo`

API entry `url`: `https://github.com/Org/My-Repo`
Normalized: `https://github.com/org/my-repo`

These do NOT match because the scheme and transport differ (`git@` vs `https://`).
Also strip common prefixes to compare just `org/my-repo`:

```
git@github.com:org/my-repo   → strip "git@github.com:" → "org/my-repo"
https://github.com/org/my-repo → strip "https://github.com/" → "org/my-repo"
```

After stripping the host, compare the path segment (`org/my-repo`). This matches.

## No Match Fallback: `git_origin` Tag

If no repo in the org's attack surface matches the local git remote, do NOT fail —
inject a `git_origin` tag into `stackhawk.yml` instead:

```yaml
tags:
  - name: git_origin
    value: <normalized-url>
```

This breadcrumb is visible in every scan from this config. Once the SCM org is
connected in StackHawk's attack surface, the platform can automap repos to apps
using the `git_origin` tag values. Use the normalized URL as the value.

### Full Phase 0a Algorithm

```
1. git remote get-url origin → LOCAL_URL
2. Normalize LOCAL_URL → NORM_LOCAL
3. hawkop repo list --format json → REPOS[]
4. For each repo in REPOS[]:
     normalize repo.url → NORM_REPO
     strip host from both → PATH_LOCAL, PATH_REPO
     if PATH_LOCAL == PATH_REPO:
       hawkop repo link --repo-id repo.id --app-id <APP_ID>
       Report: "Linked app <APP_NAME> to ASM repo <REPO_NAME>"
       DONE
5. No match found:
   Inject into stackhawk.yml tags block:
     - name: git_origin
       value: NORM_LOCAL
   Report: "No ASM repo match for NORM_LOCAL — added git_origin tag for future automapping"
```

## `hawkop repo list` Output Shape

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
ASM scan, it can inform tech flag detection (Sub-step 0c) even before inspecting
the local codebase.
