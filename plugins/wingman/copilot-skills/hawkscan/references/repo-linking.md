# Repo Linking (Attack Surface Management)

Linking a StackHawk application to its source repository enables API Discovery
tracking and SCM-driven automapping. Do this once during app onboarding (Phase 0).

## Contents
- [When to Run](#when-to-run)
- [Commands](#commands)
- [Version Guard](#version-guard)
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
# Link an existing app to a repo, found by bare repo name (additive — safe to re-run)
hawk op repo link --repo "my-repo" --app-id <APP_UUID>

# Same, when the repo name is ambiguous — target the repo by its UUID
hawk op repo link --repo-id <REPO_UUID> --app-id <APP_UUID>

# List repositories in the org's attack surface (only for the ambiguous-name case)
hawk op repo list --format json
```

`--repo` is resolved by a server-side name search, so no full repo list is downloaded.
It matches the bare repo `name` only (exact, case-insensitive), never `owner/name`.
Exit 0 with "Linked to repository …" or "… is already linked to repository …" means the
link is in place.

`--app-name "<name>"` is accepted in place of `--app-id`, but it links an **existing**
app only. If no app has that name it fails ("repo link only links existing applications")
and creates nothing. Application creation goes through SKILL.md Step 1 substep 5
(`hawk create app`), which announces the settings URL and records the `applicationId`,
so use `--app-id` with that already-resolved UUID.

```bash
# Full replacement (destructive — overwrites all existing app mappings for this repo)
# Use only if you need to remove a previously linked app
hawk op repo set-apps --repo-id <REPO_UUID> --app-ids <UUID1>,<UUID2>
```

**Prefer `repo link` over `repo set-apps`.** `link` is additive on the server: it adds
only this app, and the repo's other app mappings are left as they are. `set-apps`
replaces the entire list.

## Version Guard

`--repo` name resolution and additive `link` ship in HawkScan **6.7.4** (hawkop 0.13.0).
Older `hawk op` pages through every repo, rewrites the repo's whole app list on `link`, and
has no `id` in `repo list` JSON. Check before linking:

```bash
HAWK_V=$(hawk version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
[ "$(printf '%s\n6.7.4\n' "$HAWK_V" | sort -V | head -1)" = "6.7.4" ] \
  && echo "link: ok" || echo "link: skip"
```

If the installed hawk is older than 6.7.4, skip the `hawk op repo link` commands, print one
line (`StackHawk | Repo linking skipped - upgrade hawk to 6.7.4+ to link this app to its repo`),
and go straight to the `git_origin` tag fallback. The skill's general minimum stays 6.0.0,
so older installs still scan.

## How to Identify the Repo

1. Get the git remote URL:
   ```bash
   git remote get-url origin
   ```

2. Normalize it to the bare `owner/repo` path (`PATH_LOCAL`) in 4 steps:
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

3. `BARE_NAME` is the last path segment of `PATH_LOCAL` (`my-repo` from `org/my-repo`).

### Example

Local: `git@github.com:Org/My-Repo.git`

| Step | Value |
|------|-------|
| 1. Lowercase | `git@github.com:org/my-repo.git` |
| 2. Strip `.git` | `git@github.com:org/my-repo` |
| 3. Strip trailing `/` | `git@github.com:org/my-repo` |
| 4. Strip host (`git@github.com:`) | `org/my-repo` |

`PATH_LOCAL` = `org/my-repo`, `BARE_NAME` = `my-repo`.

## No Match Fallback: `git_origin` Tag

If no repo in the org's attack surface matches the local git remote (or the installed
hawk is older than 6.7.4), do NOT fail — inject a `git_origin` tag into `stackhawk.yml` instead:

```yaml
tags:
  - name: git_origin
    value: org/my-repo   # PATH_LOCAL, the bare path after 4-step normalization
```

Use the bare `owner/repo` path (`PATH_LOCAL`) so the platform can match
against any transport. This breadcrumb is visible in every scan from this config.
Once the SCM org is connected in StackHawk's attack surface, the platform can
automap repos to apps using the `git_origin` tag values.

### Full Phase 0a Algorithm

```
1. git remote get-url origin → LOCAL_URL
   If this command fails (no git repo or no origin remote), skip Phase 0a entirely
   and continue to Phase 0b. Repo linking is non-blocking.
2. Apply 4-step normalization to LOCAL_URL → PATH_LOCAL (bare owner/repo path)
   BARE_NAME = last path segment of PATH_LOCAL
3. Version guard: if hawk is older than 6.7.4, print the one-line upgrade note
   and go to step 5 (git_origin tag). Do not run any repo command.
4. hawk op repo link --repo "$BARE_NAME" --app-id <APP_ID>
     (where <APP_ID> is the applicationId resolved in SKILL.md Step 1 substep 5)
   exit 0 ("Linked" or "already linked")
       → Report: "Ensured link: app <APP_NAME> ↔ ASM repo <BARE_NAME>"
         DONE
   error "Ambiguous: N repositories match"
       → hawk op repo list --format json
         pick the row where lower(git_org + "/" + name) == PATH_LOCAL
         hawk op repo link --repo-id <row.id> --app-id <APP_ID>
         (if no row matches PATH_LOCAL, go to step 5)
   error "No repository found matching"
       → step 5
   any other error → report it, do not retry, go to step 5
5. No ASM repo match:
   Inject into stackhawk.yml tags block:
     - name: git_origin
       value: PATH_LOCAL
   Report: "No ASM repo match for PATH_LOCAL — added git_origin tag for future automapping"
```

`--repo` matches the bare name only. If exactly one repo in the org has that name under a
different owner (a fork's origin, say), the link goes to that repo; only two or more
same-name repos reach the `git_org/name` disambiguation.

## `hawk op repo list` Output Shape

`--format json` wraps the rows in `data`. Values are display strings (counts and flags are
strings, not numbers or booleans):

```json
{
  "data": [
    {
      "id": "uuid",
      "attack_surface": "✓",
      "provider": "GITHUB",
      "git_org": "Org",
      "name": "My-Repo",
      "oas": "✓",
      "sensitive_data": "PCI, PII",
      "last_commit": "2026-09-23T00:30:31Z",
      "last_committer": "someone",
      "commit_count": "0",
      "app_count": "1"
    }
  ]
}
```

There is no `url`, `defaultBranch`, `frameworkNames` or `appInfos` field. Match on
`git_org` + `name`, and use `id` for `--repo-id`.
