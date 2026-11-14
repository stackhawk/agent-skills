# Releasing Agent Skills

Every merge to `main` is a release. Releases follow [Semantic Versioning](https://semver.org/), are numbered by git tags alone, and are published as a `vX.Y.Z` tag, a GitHub Release and a marketplace sync. There is no `VERSION` file and no version-bump commit: do not bump anything in a PR.

## Choosing the number

`release.yml` resolves the next version (`biodome-rs ci version resolve`) as the highest release tag plus one patch. To release more than a patch, put a line in the pull request description (it becomes the squash commit message):

- `Release: minor` for new skills or significant capability
- `Release: major` for breaking changes

## What a merge does

`.github/workflows/release.yml` runs on every push to `main`, one run at a time, never cancelled:

1. **resolve** the version from the remote's tags.
2. **validate** it on a scratch copy: `scripts/bump-version.sh <version>` stamps every version-bearing file in `.version-bump.json`, the wingman Copilot bundle is regenerated, and `scripts/check-version.sh <version>` and `scripts/test-wingman-skills.sh` check the result, as do the Cursor adapter (`scripts/generate-cursor-adapter.py --check`) and the deprecated Cursor rules. Then it exports the marketplace payload of the commit (`scripts/export-marketplace.py`) and runs the marketplace sync on it in a scratch clone of the marketplace: the sync, the marketplace tests and `scripts/check-marketplace-layout.py` must pass. Nothing is committed or pushed.
3. **claim** the number (`claim/vX.Y.Z`), then draft the GitHub Release (notes are generated from the merged pull requests).
4. **tag** the merged commit `vX.Y.Z` and delete the claim. The tagged tree carries the placeholder version.
5. **publish** the GitHub Release, **sync the marketplace** and dispatch **Capture Eval Baseline** for the tag. The baseline dispatch only warns when it fails; run `Capture Eval Baseline` by hand with the tag.

Every release job runs on the `agent-skills-amd-4cpu` runner, because the `biodome-ci-*` runners do not serve public repositories. Its image has no `gh`, so the jobs that need it install the pinned, checksum-verified build from `scripts/ci/install-gh.sh`.

The tree keeps one placeholder (`0.0.0-dev`, set in `.version-bump.json`) in every version-bearing file, and the manifests whose format allows it carry no `version` (the Claude plugin manifests, `.claude-plugin/marketplace.json`, every Codex and Cursor `plugin.json`, `.cursor-plugin/marketplace.json`, the wingman Copilot manifest and the root `plugin.json`), so clients that install from the repository track the commit. `gemini-extension.json` requires a version and keeps the placeholder. A stamp adds the version to the `stamp_only` manifests and `--placeholder` removes it again. `scripts/check-version.sh` (run by `generate-and-validate.yml` on every PR) keeps it that way.

## When a release fails

A run that fails after the claim leaves `claim/vX.Y.Z` on the remote and every later run stops at resolve on it.

- If the cause was transient (runner, network, a marketplace push race), re-run the failed jobs of the release run. Every step after the tag is idempotent, and a tagged release resumes from where it stopped.
- If the merged change itself breaks the release (validate, the GitHub Release or the sync), run **Abandon release** (`abandon-release.yml`, from `main`) with the claimed number once the failed run is over, then merge the fix: its run releases the next number. An abandoned number is never reused.

## Recovering a release that was tagged wrongly

Tags are created only by the release App, so a wrong tag is deleted by an org admin. Delete the GitHub Release and the tag, then merge a fix; the next run takes the next number.

## Updating the Marketplace Catalog

The `update-marketplace` job in `.github/workflows/release.yml` runs after the release is tagged. `scripts/export-marketplace.py` exports the payload of the release tag and stamps the tag's version into its plugin manifests, SKILL.md files and generated copies, because the tagged tree carries a placeholder. The job clones [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace), runs that repository's `scripts/sync-agent-skills.py` with `--export` against the release tag, runs the marketplace tests and `scripts/check-marketplace-layout.py` on the result, and commits only the sync outputs to marketplace `main`. A rerun for an already synced tag makes no commit. If `main` advances before the push, the job fetches and rebases once, reruns the marketplace tests, then retries the push without force.

The sync script owns all marketplace release outputs:

1. **Claude plugin snapshots and catalog:** It copies the plugin snapshots of the export into `plugins/` and writes `.claude-plugin/marketplace.json` with local `./plugins/<name>` sources, so directory validation can inspect each plugin.
2. **Codex, Copilot and Cursor catalogs and wingman bundle:** It points catalog sources at marketplace paths and copies the wingman bundle of the export to `bundles/wingman/`. The Cursor catalog comes from the export.
3. **Standalone skills:** It rebuilds `skills/` for the [`skills` CLI](https://github.com/vercel-labs/skills), which discovers `SKILL.md` files and ignores marketplace catalogs.
4. **Installers:** It copies `install/` of the export: `install.sh`, `install.ps1` and `cursor-legacy-rules.txt`.

Review the resulting commit on marketplace `main` after the job succeeds. In its checkout, run `claude plugin validate --strict .`, validate each `plugins/<name>` folder, and run `python3 -m unittest discover -s tests`. The release job runs the marketplace tests before pushing. The separate `Marketplace Install Verify` workflow in this repository tests catalog compatibility and standalone skill discovery from local fixtures.

If the workflow fails, inspect the job logs, fix the cause, and re-run the failed jobs of the release run. Do not hand-edit generated catalogs, plugin snapshots, or standalone skills.

## Cursor distribution prerequisites

This repository builds what the marketplace publishes. `scripts/export-marketplace.py` writes the release payload of one commit, and `scripts/check-marketplace-layout.py` checks the payload and the synced marketplace. The export reads the commit with `git archive`, never the working tree, stamps the version as the validate job does, and writes the same bytes for the same commit and version.

| Export path | Content |
|---|---|
| `plugins/<name>/` | Each plugin of `.claude-plugin/marketplace.json`, named by its catalog name, as Claude Code installs it. `wingman` leaves out `copilot-skills/`, `.github/`, `.cursor-plugin/`, `rules/` and `hooks/cursor/`. |
| `bundles/wingman/` | All of `plugins/wingman`, for Copilot, Codex and Cursor, which do not install plugin dependencies. |
| `.cursor-plugin/marketplace.json` | The Cursor catalog, with `./plugins/<name>` sources and `./bundles/wingman` for wingman. |
| `install/` | `install.sh`, `install.ps1` and `cursor-legacy-rules.txt`. |
| `export-manifest.json` | The commit, the version, and the mode, size and sha256 of every other file. |

The Claude snapshot of `wingman` leaves out the Cursor files because the Cursor desktop app imports Claude Code plugins by default (`importPluginsFromClaudeOnBoot`; inferred from the Cursor 3.9.16 code, not observed). A Claude Code user with `wingman` also has its `hawkscan` dependency, so those files would load the router rule and the stop hook a second time. The layout check counts the router rules, stop hooks, rules and skills of every Claude Code install (a plugin with its dependencies) with each manifest that Cursor could read, and of every Cursor catalog install. It also requires the Cursor catalog, every path a Cursor manifest names, the hook scripts, the installers and the legacy rule list. With `--version`, every Cursor manifest and SKILL.md must carry that version. With `--run-installers`, it runs `install/install.sh` (and `install/install.ps1` when `pwsh` is installed) into a scratch project and checks the skills, rules and stop hook it installs; the export and the release always use it. The docstring of the check names what it assumes about Cursor and which combined installs it does not count.

The installers find each skill by its catalog plugin name in a snapshot (`plugins/stackhawk-api/skills/api`) and by its source folder in a clone (`plugins/api/skills/api`), and they read `cursor-legacy-rules.txt` from their own folder. So `install/install.sh` in a marketplace checkout installs the released, stamped skills. `scripts/install.sh` in a clone of `main` installs unreleased skills that carry the placeholder version.

### Rollout order

The marketplace change below ships first. The validate job of every release runs the marketplace sync with `--export` and stages its outputs with `scripts/ci/stage-marketplace-sync.sh`, so until the marketplace sync accepts that option and writes `install/` and `.cursor-plugin/marketplace.json`, validate fails and no merge claims a release number. Once the marketplace change is on its `main`, the next release publishes the Cursor catalog, the installers and a Claude `wingman` with no Cursor files. After that release, point the README's Cursor users at the marketplace.

### Marketplace change

In [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace):

1. `scripts/sync-agent-skills.py` gets an `--export DIR` option. With it, the sync:
   - checks `export-manifest.json`: the tag's commit and version, the upstream folder of every plugin in `sources.json`, and the sha256 of every file;
   - copies `plugins/<name>` and `bundles/wingman` from the export, not from the tag's plugin folders, and gives the bundle the snapshot's Claude manifest;
   - stamps `.cursor-plugin/plugin.json` with the other manifests;
   - writes the export's Cursor catalog, limited to the plugins in `sources.json`, and copies `install/`;
   - adds `.cursor-plugin/marketplace.json` and `install` to the paths that `install()` replaces.
   Without `--export`, the sync keeps its old path, for tags older than the export.
2. The tests cover the Cursor catalog, the installers, a Claude `plugins/wingman` with no `.cursor-plugin/`, `rules/` or `hooks/`, and the export mode, including an export of another commit and a changed file.
3. The README describes the Cursor install (team marketplace import and `install/install.sh`) and the hand sync below.
4. `.gitattributes` gets `*.sh text eol=lf`, as here, so a Windows checkout keeps LF in `install/install.sh` and the stop hook.

The first sync with `--export` then adds `.cursor-plugin/marketplace.json`, `install/`, a `.cursor-plugin/plugin.json` in each component plugin, `plugins/hawkscan/rules/`, `plugins/hawkscan/hooks/cursor/plugin-hooks.json`, and `.cursor-plugin/`, `rules/` and `hooks/cursor/` in `bundles/wingman/`. It changes `sources.json` and the version and content of the other generated files, as every release does. It adds no file to `plugins/wingman/`.

### Hand sync

```bash
# In an agent-skills checkout that has the release tag:
python3 scripts/export-marketplace.py --ref vX.Y.Z --version X.Y.Z --dest /tmp/agent-skills-export
# In the marketplace checkout:
python3 scripts/sync-agent-skills.py --source-repo /path/to/agent-skills --tag vX.Y.Z \
  --export /tmp/agent-skills-export
python3 -m unittest discover -s tests
python3 /path/to/agent-skills/scripts/check-marketplace-layout.py --run-installers --version X.Y.Z .
```

### Known gap

This repository is also a Claude Code marketplace (`/plugin marketplace add stackhawk/agent-skills`), and its catalog lists `plugins/wingman`, which carries the Cursor files. A Claude Code user who installs `wingman` from this repository, not from the marketplace, gets the double import in Cursor. `python3 scripts/check-marketplace-layout.py --no-installers .` shows it. To remove it, this repository needs a Cursor wingman folder that its Claude catalog does not list. That is a change to the source layout, and a separate decision.
