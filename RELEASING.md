# Releasing Agent Skills

Every merge to `main` is a release. Releases follow [Semantic Versioning](https://semver.org/), are numbered by git tags alone, and are published as a `vX.Y.Z` tag, a GitHub Release and a marketplace sync. There is no `VERSION` file and no version-bump commit: do not bump anything in a PR.

## Choosing the number

`release.yml` resolves the next version (`biodome-rs ci version resolve`) as the highest release tag plus one patch. To release more than a patch, put a line in the pull request description (it becomes the squash commit message):

- `Release: minor` for new skills or significant capability
- `Release: major` for breaking changes

## What a merge does

`.github/workflows/release.yml` runs on every push to `main`, one run at a time, never cancelled:

1. **resolve** the version from the remote's tags.
2. **validate** it on a scratch copy: `scripts/bump-version.sh <version>` stamps every version-bearing file in `.version-bump.json`, the wingman Copilot bundle is regenerated, and `scripts/check-version.sh <version>` and `scripts/test-wingman-skills.sh` check the result, as do the Cursor adapter (`scripts/generate-cursor-adapter.py --check`) and the deprecated Cursor rules. Nothing is committed.
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

The `update-marketplace` job in `.github/workflows/release.yml` runs after the release is tagged. The sync takes the version from the tag and stamps it into the plugin manifests, SKILL.md files and generated copies of its snapshot, because the tagged tree carries a placeholder. It clones [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace), runs that repository's `scripts/sync-agent-skills.py` against the release tag, validates its generated layout, and commits only the sync outputs to marketplace `main`. A rerun for an already synced tag makes no commit. If `main` advances before the push, the job fetches and rebases once, reruns the marketplace tests, then retries the push without force.

The sync script owns all marketplace release outputs:

1. **Claude plugin snapshots and catalog:** It copies the released plugin folders into `plugins/` and writes `.claude-plugin/marketplace.json` with local `./plugins/<name>` sources, so directory validation can inspect each plugin.
2. **Codex and Copilot catalogs and wingman bundle:** It points catalog sources at marketplace paths and writes the Copilot and Codex wingman bundle under `bundles/wingman/`.
3. **Standalone skills:** It rebuilds `skills/` for the [`skills` CLI](https://github.com/vercel-labs/skills), which discovers `SKILL.md` files and ignores marketplace catalogs.

Review the resulting commit on marketplace `main` after the job succeeds. In its checkout, run `claude plugin validate --strict .`, validate each `plugins/<name>` folder, and run `python3 -m unittest discover -s tests`. The release job runs the marketplace tests before pushing. The separate `Marketplace Install Verify` workflow in this repository tests catalog compatibility and standalone skill discovery from local fixtures.

If the workflow fails, inspect the job logs, fix the cause, and re-run the failed jobs of the release run. Do not hand-edit generated catalogs, plugin snapshots, or standalone skills.

## Cursor distribution prerequisites

This repository ships the Cursor adapter: a `.cursor-plugin/plugin.json` in every plugin folder, `.cursor-plugin/marketplace.json` at the root, the rules in `plugins/hawkscan/rules/`, and the Cursor hooks in `plugins/hawkscan/hooks/cursor/` (`scripts/generate-cursor-adapter.py` writes the manifests and the wingman copies). The marketplace sync already copies every file in a plugin folder into the released snapshot. A released Cursor install through a team marketplace import of [stackhawk/agent-skills-marketplace](https://github.com/stackhawk/agent-skills-marketplace) also needs these changes in that repository. Until they ship, Cursor users install from a clone of this repository (`scripts/install.sh`, or `cursor-agent --plugin-dir`).

1. `prepare_catalogs` in `scripts/sync-agent-skills.py` writes `.cursor-plugin/marketplace.json`, with `./plugins/<name>` sources and `./bundles/wingman` for wingman. Only the bundle keeps `copilot-skills/`, which the wingman Cursor manifest loads.
2. `stamp_versions` stamps `.cursor-plugin/plugin.json` with the other manifests.
3. `split_bundle` removes `.cursor-plugin/`, `rules/` and `hooks/cursor/` from the Claude-listed `plugins/wingman` and keeps them in `bundles/wingman`. **Ship this item before the first release that contains the Cursor adapter**, not only with the Cursor catalog: the Claude snapshot of `wingman` carries those files from that release on. The Cursor desktop app imports Claude Code plugins by default (`importPluginsFromClaudeOnBoot`), so a Claude Code user with `wingman` would get the router rule and the stop hook twice, once from `hawkscan` and once from `wingman`. This is inferred from the Cursor 3.9.16 code, not observed.
4. `install()` adds `.cursor-plugin/marketplace.json` to its paths, and the `git add` list of the `update-marketplace` job in `release.yml` adds the same path. Without it the "changes outside the staged paths" check fails the release.
5. The marketplace tests cover the Cursor catalog, and the marketplace README describes the Cursor install.

`scripts/install.sh` still copies from the checkout it runs in, normally a clone of `main`, so it installs unreleased skills that carry the placeholder version. It can install a released snapshot only after the steps above have shipped and one release has synced the Cursor files into the marketplace. It also needs two changes then: the sync must copy `scripts/install.sh`, `scripts/install.ps1` and `scripts/cursor-legacy-rules.txt` into the snapshot, and the installers must find each skill by its catalog plugin name, because the snapshot names plugin folders by that name (`plugins/stackhawk-api/skills/api`, not `plugins/api/skills/api`). Test it against a local sync of a release tag before the README points Cursor users at the marketplace repository.
