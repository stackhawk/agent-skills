# Releasing Agent Skills

Every merge to `main` is a release. Releases follow [Semantic Versioning](https://semver.org/), are numbered by git tags alone, and are published as a `vX.Y.Z` tag, a GitHub Release and a marketplace sync. There is no `VERSION` file and no version-bump commit: do not bump anything in a PR.

## Choosing the number

`release.yml` resolves the next version (`biodome-rs ci version resolve`) as the highest release tag plus one patch. To release more than a patch, put a line in the pull request description (it becomes the squash commit message):

- `Release: minor` for new skills or significant capability
- `Release: major` for breaking changes

## What a merge does

`.github/workflows/release.yml` runs on every push to `main`, one run at a time, never cancelled:

1. **resolve** the version from the remote's tags.
2. **validate** it on a scratch copy: `scripts/bump-version.sh <version>` stamps every version-bearing file in `.version-bump.json`, the wingman bundled skills are regenerated, and `scripts/check-version.sh <version>`, `scripts/test-wingman-skills.sh` and the source layout check (`scripts/check-marketplace-layout.py --no-installers .`) check the result, as do the Cursor adapter (`scripts/generate-cursor-adapter.py --check`) and the deprecated Cursor rules. Then it exports the marketplace payload of the commit (`scripts/export-marketplace.py`) and runs the marketplace sync on it in a scratch clone of the marketplace: the sync, the marketplace tests and `scripts/check-marketplace-layout.py` must pass. Nothing is committed or pushed.
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
2. **Codex, Copilot and Cursor catalogs and wingman bundle:** It points catalog sources at marketplace paths, copies the wingman bundle of the export to `bundles/wingman/`, and copies the Cursor-only hawkscan of the export to `cursor-plugins/hawkscan/`. The Cursor catalog comes from the export.
3. **Standalone skills:** It rebuilds `skills/` for the [`skills` CLI](https://github.com/vercel-labs/skills), which discovers `SKILL.md` files and ignores marketplace catalogs.
4. **Installers:** It copies `install/` of the export: `install.sh`, `install.ps1` and `cursor-legacy-rules.txt`.

Review the resulting commit on marketplace `main` after the job succeeds. In its checkout, run `claude plugin validate --strict .`, validate each `plugins/<name>` folder, and run `python3 -m unittest discover -s tests`. The release job runs the marketplace tests before pushing. The separate `Marketplace Install Verify` workflow in this repository tests catalog compatibility and standalone skill discovery from local fixtures.

If the workflow fails, inspect the job logs, fix the cause, and re-run the failed jobs of the release run. Do not hand-edit generated catalogs, plugin snapshots, or standalone skills.

## Cursor distribution prerequisites

This repository builds what the marketplace publishes. `scripts/export-marketplace.py` writes the release payload of one commit, and `scripts/check-marketplace-layout.py` checks the payload and the synced marketplace. The export reads the commit with `git archive`, never the working tree. It refuses a commit whose generated files (the wingman skill copies, the Cursor adapter) differ from what its sources give, stamps the version as the validate job does, and writes the same bytes for the same commit and version. `--verify DIR` checks an export that exists: see "Hand sync".

### Source layout

The Cursor app and the Cursor CLI import Claude Code plugins: their skills, rules and hooks. Cursor reads a plugin's `.cursor-plugin/plugin.json` first, then its Claude manifest, and it runs Claude Code hooks for the matching Cursor events (`SessionStart` as `sessionStart`, `PostToolUse` as `postToolUse`, `Stop` as `stop`). The Cursor CLI 2026.11.13 ran the `SessionStart` hook of an imported plugin in a live headless run; the app import is inferred from the Cursor 3.9.16 code (`importPluginsFromClaudeOnBoot`), not observed. So a Claude Code install would give Cursor a second router rule and stop hook next to the one native Cursor install, unless the Claude-listed folders keep them out:

- No Claude-listed folder carries a Cursor rule or Cursor hook. The Claude-listed folders of `hawkscan` and `wingman` carry no Cursor file at all.
- The Claude Code hooks of `plugins/hawkscan` do nothing when Cursor runs them. Each script first sources `plugins/hawkscan/hooks/skip-under-cursor`, which ends the hook when `CURSOR_VERSION` or `CURSOR_PROJECT_DIR` is set and `CLAUDECODE` is not. Cursor sets those variables for every hook and never sets `CLAUDECODE`; Claude Code 2.1.325 sets `CLAUDECODE=1` for every hook. Each host passes on what it inherited, so Cursor started from a Claude Code shell runs hooks with both: then the payload decides. Every Cursor hook payload has a top-level `cursor_version` key and no Claude Code payload has one, so the guard ends the hook only for such a payload, and else gives the payload back to the hook.

| Source folder | Listed by | Content |
|---|---|---|
| `cursor-src/` | no catalog | The hand-written Cursor parts: the router rule `rules/stackhawk.mdc`, the config rule `rules/stackhawk-config.mdc`, the stop hook `hooks/stop.sh`, the project hook config `hooks/hooks.json` and the plugin hook config `hooks/plugin-hooks.json`. |
| `plugins/hawkscan/` | the Claude and Codex catalogs | The skill, the Claude Code hooks and the Claude and Codex manifests. No Cursor file. |
| `cursor-plugins/hawkscan/` | the Cursor catalog only | Its Cursor manifest, a copy of the skill in `skills/`, the two rules, the Cursor hooks in `hooks/cursor/` and a README. All generated. The installers read the rules and the stop hook from here. |
| `plugins/wingman/` | the Claude and Codex catalogs (and Copilot, which reads the Claude catalog) | The Claude, Codex and Copilot manifests, `README.md`, and `copilot-skills/`, the bundled copies of the four skills. No Cursor file. |
| `cursor-plugins/wingman/` | the Cursor catalog only | Its Cursor manifest, its own copies of the four skills in `skills/`, the two rules, the Cursor stop hook and a README. All generated. |

`scripts/generate-wingman-skills.sh` writes the three skill copies (`plugins/wingman/copilot-skills/`, `cursor-plugins/wingman/skills/` and `cursor-plugins/hawkscan/skills/`) in one run. `scripts/generate-cursor-adapter.py` writes the rest of `cursor-plugins/` from `cursor-src/`. Its `--check` fails on a missing, changed, stale or not executable file there, on CRLF line endings and on a symlink, on skill copies that differ, on a Cursor rule or hook in a Claude-listed folder, on any Cursor file (a Cursor manifest, `rules/`, `hooks/cursor/` or any `.mdc`) in `plugins/hawkscan` or `plugins/wingman`, and on a Claude or Codex catalog that lists `cursor-plugins/` or `cursor-src/`. Every other plugin serves both catalogs from its `plugins/<name>` folder, and its Cursor manifest names only its skills. `python3 scripts/check-marketplace-layout.py --no-installers .` checks the source catalogs as the release checks the marketplace.

### Export layout

| Export path | Content |
|---|---|
| `plugins/<name>/` | Each plugin of `.claude-plugin/marketplace.json`, named by its catalog name, as Claude Code installs it. `wingman` leaves out its Copilot and Codex parts (`copilot-skills/`, `.github/`). The export refuses a Claude plugin with a Cursor rule or hook, and a `plugins/hawkscan` or `plugins/wingman` with any Cursor file. |
| `bundles/wingman/` | `plugins/wingman` with the Cursor parts (`.cursor-plugin/`, `rules/`, `hooks/cursor/`) of `cursor-plugins/wingman`, for Copilot, Codex and Cursor, which do not install plugin dependencies. The bundle keeps one copy of the four skills, `copilot-skills/`, and its Cursor manifest names it; the export refuses `cursor-plugins/wingman/skills/` copies that differ from it. |
| `cursor-plugins/hawkscan/` | `cursor-plugins/hawkscan` as in the source, without its README. The export refuses a `skills/` copy that differs from `plugins/hawkscan/skills/`, and a file that a Cursor-only folder does not hold. |
| `.cursor-plugin/marketplace.json` | The Cursor catalog, with `./plugins/<name>` sources, `./bundles/wingman` for wingman and `./cursor-plugins/hawkscan` for hawkscan. |
| `install/` | `install.sh`, `install.ps1` and `cursor-legacy-rules.txt`. |
| `export-manifest.json` | The format (`2`), the commit, the version, the source folders of each plugin and of the bundle (`plugins`, `bundles`), the export folder that the Cursor catalog installs each plugin from (`cursor`), and the mode, size and sha256 of every other file. Format 2 added `cursor-plugins/hawkscan/` and the `cursor` map, and removed `cursor_folders`; a sync that reads format 1 refuses it. |

The layout check counts the router rules, stop hooks, rules and skills of every Cursor catalog install, of the project install and of the user-level install (its stop hook alone, because Cursor has no file-based user rules). It runs each stop hook as Cursor runs it (`scripts/cursor-hook-probe.py`) and counts only the hooks that act. It also loads every Claude Code install (a plugin with its dependencies) as Cursor imports it, alone and with each native Cursor install: alone, it must give no rule and no hook that acts; with a native install, the router rules and acting stop hooks must be those of the native install. It does not count the skills of a combined install, because Cursor lists the skills of both channels. It also requires the Cursor catalog, every path a Cursor manifest names, the hook scripts, the installers and the legacy rule list. With `--version`, every Cursor manifest and SKILL.md must carry that version. With `--run-installers`, it runs `install/install.sh` (and `install/install.ps1` when `pwsh` is installed) into a scratch project and checks the skills, rules and stop hook it installs; the export and the release always use it. The docstring of the check names what it assumes about Cursor and which combined installs it does not count.

The installers find each skill by its catalog plugin name in a snapshot (`plugins/stackhawk-api/skills/api`) and by its source folder in a clone (`plugins/api/skills/api`), and they read `cursor-legacy-rules.txt` from their own folder. So `install/install.sh` in a marketplace checkout installs the released, stamped skills. `scripts/install.sh` in a clone of `main` installs unreleased skills that carry the placeholder version.

### Rollout order

The marketplace change below ships first. The validate job of every release runs the marketplace sync with `--export` and stages its outputs with `scripts/ci/stage-marketplace-sync.sh`, so until the marketplace sync accepts that option, reads export format 2 and writes `install/`, `cursor-plugins/` and `.cursor-plugin/marketplace.json`, validate fails and no merge claims a release number. Once the marketplace change is on its `main`, the next release publishes the Cursor catalog, the installers, the Cursor-only `hawkscan`, and Claude `hawkscan` and `wingman` plugins with no Cursor files. A later change of the export format ships the same way: the marketplace reads the new format first. The README points users at the marketplace, and Cursor users at the development build until that release.

### Marketplace change

In [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace):

1. `scripts/sync-agent-skills.py` gets an `--export DIR` option. With it, the sync:
   - checks `export-manifest.json`: its format (`2`), the tag's commit and version, the upstream folder of every plugin in `sources.json`, the folder that Cursor installs every plugin from (`cursor`), and the sha256 of every file;
   - copies `plugins/<name>`, `bundles/wingman` and each `cursor-plugins/<name>` from the export, not from the tag's plugin folders, and gives the bundle the snapshot's Claude manifest;
   - stamps `.cursor-plugin/plugin.json` with the other manifests;
   - refuses a Claude snapshot with a Cursor rule or Cursor hook, and a Claude snapshot with any Cursor file when Cursor installs that plugin from another folder;
   - writes the export's Cursor catalog, limited to the plugins in `sources.json`, and copies `install/`;
   - adds `.cursor-plugin/marketplace.json`, `cursor-plugins` and `install` to the paths that `install()` replaces.
   Without `--export`, the sync keeps its old path, for tags older than the export.
2. The tests cover the Cursor catalog, the installers, the Cursor-only `hawkscan`, Claude `plugins/hawkscan` and `plugins/wingman` snapshots with no `.cursor-plugin/`, `rules/` or `hooks/cursor/`, the `cursor` map, and the export mode, including an export of another commit or format and a changed file.
3. The README describes the Cursor install (team marketplace import and `install/install.sh`) and the hand sync below.
4. `.gitattributes` gets `*.sh text eol=lf`, as here, so a Windows checkout keeps LF in `install/install.sh` and the stop hook.

The first sync with `--export` then adds `.cursor-plugin/marketplace.json`, `install/`, `cursor-plugins/hawkscan/`, a `.cursor-plugin/plugin.json` in each component plugin other than `hawkscan`, the hook guard `plugins/hawkscan/hooks/skip-under-cursor`, and `.cursor-plugin/`, `rules/` and `hooks/cursor/` in `bundles/wingman/`. It removes `plugins/hawkscan/hooks/cursor/`, the project hook files that the Claude snapshot of `hawkscan` carried. It changes `sources.json` and the version and content of the other generated files, as every release does. It adds no Cursor file to `plugins/hawkscan/` or `plugins/wingman/`.

### Hand sync

```bash
# In an agent-skills checkout that has the release tag:
python3 scripts/export-marketplace.py --ref vX.Y.Z --version X.Y.Z --dest /tmp/agent-skills-export
python3 scripts/export-marketplace.py --ref vX.Y.Z --version X.Y.Z --verify /tmp/agent-skills-export
# In the marketplace checkout:
python3 scripts/sync-agent-skills.py --source-repo /path/to/agent-skills --tag vX.Y.Z \
  --export /tmp/agent-skills-export
python3 -m unittest discover -s tests
python3 /path/to/agent-skills/scripts/check-marketplace-layout.py --run-installers --version X.Y.Z .
bash /path/to/agent-skills/scripts/ci/stage-marketplace-sync.sh .
```

`--verify` fails on an export of another commit or version, a file that is missing, changed, not listed or a symlink, a path outside the layout, and CRLF line endings. Then it exports the commit again and compares the manifests, so a changed file whose manifest entry was changed to match fails too.

### Direct installs from this repository

This repository is also a Claude Code, Codex and Cursor marketplace (`/plugin marketplace add stackhawk/agent-skills`). It is for development builds; users install from the marketplace. A direct install is still safe: the Claude catalog lists `plugins/hawkscan` and `plugins/wingman` with no Cursor file, so a Claude Code install that Cursor imports loads no router rule and no stop hook that acts, and the Cursor catalog install of `cursor-plugins/hawkscan` or `cursor-plugins/wingman` loads one of each. That Claude Code install next to one Cursor catalog install or one project install loads one of each, from the Cursor install, and next to a user-level install only its stop hook. Two Cursor channels, for example a project install and a Cursor catalog install, or a user-level install and either of them, load two stop hooks; the README tells users to use one Cursor channel per project.
