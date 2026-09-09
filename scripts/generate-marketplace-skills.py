#!/usr/bin/env python3
"""Vendor the released skill directories into the agent-skills-marketplace repo.

The marketplace repo (stackhawk/agent-skills-marketplace) publishes plugin
CATALOGS (marketplace.json per flavor, see generate-marketplace-catalogs.py)
that point back at this repo at a tagged release. Claude Code, Codex, and
Copilot all read those catalogs. The `skills` CLI (vercel-labs/skills, run as
`npx skills add stackhawk/agent-skills-marketplace`) does NOT: it ignores
marketplace.json entirely and discovers skills by walking the GitHub tree of the
DEFAULT BRANCH for SKILL.md files. A catalog-only marketplace therefore looks
empty to it.

So the release publisher (release.yml `update-marketplace`) also runs this
script, which copies each curated plugin's skill directory into
`<out-dir>/skills/<plugin-name>/` — symlinks dereferenced, because this repo
reaches skills through symlinks and the marketplace repo has no plugins/ tree for
them to point at. Why vendor into the marketplace repo rather than point the CLI
at this repo? Because the CLI tracks the default branch, so publishing only on
release gives GA cadence (the marketplace default branch only ever holds released
skills), whereas this repo's main holds in-development work. `npx skills update`
re-fetches the GitHub tree and compares per-folder content hashes against the
installed copy, so a full rebuild here (stale files removed) is what makes an
update land exactly the released content.

Curation is in lockstep with the catalogs: the default plugin list is
DEFAULT_PLUGINS imported from generate-marketplace-catalogs.py, minus `wingman`.
Wingman is a meta-plugin with no skills/ directory by design (it bundles its
dependencies under copilot-skills/ instead) and must never get a vendored entry.

Plugin name -> source skill dir is resolved via the repo-root `skills/<name>`
symlinks (e.g. skills/stackhawk-api -> ../plugins/api/skills/api). Where the
plugin name differs from the source skill's frontmatter `name:` (api,
optimize), ONLY the vendored copy's first `name:` line is rewritten to the plugin
name — exactly as generate-wingman-skills.sh does — so `npx skills add` shows
the namespaced `stackhawk-api` / `stackhawk-optimize`. Sources are untouched.

Usage:
  generate-marketplace-skills.py --out-dir DIR [--plugins hawkscan,stackhawk-api | all]
"""
import argparse
import importlib.util
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_LINKS_DIR = os.path.join(REPO_ROOT, "skills")
CATALOGS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "generate-marketplace-catalogs.py")

# Plugins that must never be vendored, even when requested via --plugins.
EXCLUDED_PLUGINS = frozenset({"wingman"})

# Matches the first `name:` line (frontmatter). Skill bodies contain YAML examples
# with their own name: keys, so we rewrite exactly one match, never globally.
NAME_LINE = re.compile(r"^name:[ \t]*(.*)$", re.MULTILINE)

README_TEXT = """# GENERATED — do not edit

Produced by `scripts/generate-marketplace-skills.py` in stackhawk/agent-skills on
every release. Edit the source skills under `plugins/*/skills/*/` in that repo and
cut a release; the next publish fully rebuilds this directory.

These vendored copies exist for the `skills` CLI (`npx skills add
stackhawk/agent-skills-marketplace`), which discovers SKILL.md files in this
repo's default branch and ignores the plugin catalogs (marketplace.json). Claude
Code, Codex, and Copilot install via the catalogs and never read this directory.
"""


def load_default_plugins():
    """Import DEFAULT_PLUGINS from the sibling catalog generator. Its filename has
    hyphens, so a plain `import` cannot reach it; load it from its path."""
    spec = importlib.util.spec_from_file_location("generate_marketplace_catalogs", CATALOGS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.DEFAULT_PLUGINS)


def parse_plugins(raw, defaults):
    """Resolve --plugins into an ordered list. "all" means the full default set;
    the excluded set (wingman) is dropped from defaults and rejected if named."""
    if raw.strip().lower() == "all":
        return [p for p in defaults if p not in EXCLUDED_PLUGINS]
    requested = [x.strip() for x in raw.split(",") if x.strip()]
    banned = [p for p in requested if p in EXCLUDED_PLUGINS]
    if banned:
        fail(f"plugins have no skills/ dir by design and cannot be vendored: {banned}")
    return requested


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def resolve_source(plugin):
    """skills/<plugin> symlink -> real source dir. Fails loudly if the link or its
    SKILL.md is missing, so a curation typo never yields a silently empty skill."""
    link = os.path.join(SKILL_LINKS_DIR, plugin)
    if not os.path.islink(link):
        fail(f"no skills/{plugin} symlink in repo root (unknown plugin?)")
    source = os.path.realpath(link)
    if not os.path.isfile(os.path.join(source, "SKILL.md")):
        fail(f"skills/{plugin} -> {source} has no SKILL.md")
    return source


def read_first_name(skill_md):
    with open(skill_md) as f:
        match = NAME_LINE.search(f.read())
    return match.group(1).strip() if match else None


def rewrite_first_name(skill_md, new_name):
    """Rewrite only the first `name:` line, then verify the result."""
    with open(skill_md) as f:
        text = f.read()
    rewritten = NAME_LINE.sub(f"name: {new_name}", text, count=1)
    with open(skill_md, "w") as f:
        f.write(rewritten)
    if read_first_name(skill_md) != new_name:
        fail(f"failed to rewrite name in {skill_md}")


def vendor_skill(source, dest, plugin):
    """Copy one skill (symlinks dereferenced) and namespace its frontmatter name."""
    shutil.copytree(source, dest, symlinks=False)
    skill_md = os.path.join(dest, "SKILL.md")
    src_name = read_first_name(skill_md)
    if src_name == plugin:
        print(f"vendored skills/{plugin}")
        return
    rewrite_first_name(skill_md, plugin)
    print(f"vendored skills/{plugin} (name: {src_name} -> {plugin})")


def write_readme(skills_dir):
    with open(os.path.join(skills_dir, "README.md"), "w") as f:
        f.write(README_TEXT)


def main():
    ap = argparse.ArgumentParser(description="Vendor released skills into the marketplace repo.")
    ap.add_argument("--out-dir", required=True, help="Output dir (marketplace repo root)")
    ap.add_argument("--plugins", default="all",
                    help='Comma-separated plugin names, or "all" (default; DEFAULT_PLUGINS minus wingman).')
    args = ap.parse_args()

    plugins = parse_plugins(args.plugins, load_default_plugins())
    if not plugins:
        fail("no plugins to vendor")

    # Validate every source BEFORE deleting anything — a bad name must not leave
    # the marketplace half-emptied.
    sources = {plugin: resolve_source(plugin) for plugin in plugins}

    # Full rebuild so files deleted from source do not linger in the marketplace.
    skills_dir = os.path.join(args.out_dir, "skills")
    shutil.rmtree(skills_dir, ignore_errors=True)
    os.makedirs(skills_dir)

    for plugin, source in sources.items():
        vendor_skill(source, os.path.join(skills_dir, plugin), plugin)
    write_readme(skills_dir)
    print(f"Done. Vendored {len(sources)} skill(s) into {skills_dir}")


if __name__ == "__main__":
    main()
