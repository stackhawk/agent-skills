#!/usr/bin/env python3
"""Generate the Cursor adapter from the canonical plugins.

Cursor reads the canonical skills (plugins/*/skills/) as Agent Skills. This script writes
only what Cursor needs beyond them, and never copies a skill body into a rule:

  <folder>/.cursor-plugin/plugin.json   one per plugin in .claude-plugin/marketplace.json, in
                                         the folder that the Cursor catalog installs it from
  .cursor-plugin/marketplace.json        the catalog for a Cursor team marketplace import
  cursor-plugins/wingman/                the rest of the Cursor-only wingman plugin: copies of
                                         hawkscan's rules and Cursor plugin hooks, and README.md

Every plugin but the umbrella wingman serves Claude Code and Cursor from one folder under
plugins/. Wingman cannot. Claude Code installs its dependencies, and the hawkscan dependency
carries the router rule and the stop hook. The Cursor app imports Claude Code plugins, and
Cursor has no plugin dependencies. So the Claude catalog lists plugins/wingman, which must
carry no Cursor file (.cursor-plugin/, rules/, hooks/cursor/), and the Cursor catalog lists
cursor-plugins/wingman, which no Claude or Codex catalog may list. Its skills/ holds copies
of the four bundled skills: scripts/generate-wingman-skills.sh writes them in the same run as
plugins/wingman/copilot-skills/, and this script checks that the two are identical. This
script owns every other file under cursor-plugins/. --check fails on a missing, changed
(CRLF line endings included), stale or wrongly executable file and on a symlink there; a write
removes stale files. .gitattributes keeps these copies and their sources LF in every checkout.
The executable bit is compared only where git tracks it: with core.fileMode=false (a FAT or
/mnt/c checkout, where every file shows as executable) git ignores it, and so does --check.

The hand-written sources are plugins/hawkscan/rules/*.mdc and plugins/hawkscan/hooks/cursor/.
The script also enforces the rule budgets: every rule is always-applied or glob-scoped,
always-applied bodies total at most 2,000 bytes and 40 lines each, a glob rule is at most
1,200 bytes, the always-applied router names every public skill and no other, and no rule
holds a markdown link or a references/ path (rules sit outside the skill folders, so such
a path does not resolve).

Manifests carry no version in the tree (stamp_only in .version-bump.json). When a release
stamp has added one, the script keeps it, so --check passes on a stamped tree.

Usage:
  generate-cursor-adapter.py [--check] [--root DIR]
"""
import argparse
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

ROUTER_MAX_BYTES = 2000
RULE_MAX_LINES = 40
GLOB_RULE_MAX_BYTES = 1200

RULES_SOURCE = "plugins/hawkscan/rules"
HOOKS_SOURCE = "plugins/hawkscan/hooks/cursor"
PLUGIN_HOOKS = "plugin-hooks.json"
HOOK_SCRIPT = "stop.sh"

# Cursor-only plugins: catalog name -> the folder the Cursor catalog installs it from. Only
# the Cursor catalog may list a folder under CURSOR_ONLY_ROOT.
CURSOR_ONLY_ROOT = "cursor-plugins"
CURSOR_ONLY = {"wingman": f"{CURSOR_ONLY_ROOT}/wingman"}
# What Cursor reads from a plugin folder beyond its skills. The Claude-listed folder of a
# Cursor-only plugin carries none of it.
CURSOR_PARTS = (".cursor-plugin", "rules", "hooks/cursor")
# The skill copies of a Cursor-only plugin, and the Claude-listed copies that they equal.
CURSOR_ONLY_SKILLS = "skills"
BUNDLED_SKILLS = "copilot-skills"
BUNDLED_SKILLS_README = "README.md"
WINGMAN_BUNDLED_SKILLS = f"plugins/wingman/{BUNDLED_SKILLS}"

# Cursor component paths per catalog plugin. Plugins not listed use Cursor's default
# skills/ folder and carry no rules or hooks. The Cursor manifest never names the
# Claude-format hooks/hooks.json, so Cursor runs its native hooks file and Claude Code
# keeps its own.
ADAPTER = {
    "hawkscan": {"rules": "./rules/", "hooks": f"./hooks/cursor/{PLUGIN_HOOKS}"},
    # Cursor has no plugin dependencies, so the Cursor-only umbrella carries its own copies
    # of the bundled skills.
    "wingman": {"skills": f"./{CURSOR_ONLY_SKILLS}/", "rules": "./rules/",
                "hooks": f"./hooks/cursor/{PLUGIN_HOOKS}"},
}

CATALOG_DESCRIPTION = (
    "Official StackHawk plugins for Cursor. Dynamic application and API security testing "
    "(DAST) powered by HawkScan."
)
CATALOG_ENTRY_KEYS = ("name", "source", "description", "category", "homepage")

CURSOR_ONLY_README = """\
# GENERATED - do not edit

The Cursor-only `{name}` plugin. Only the Cursor catalog (`.cursor-plugin/marketplace.json`)
lists this folder. The Claude and Codex catalogs list `{claude}`.

Claude Code installs the dependencies of `{name}`, and the `hawkscan` dependency carries the
router rule and the stop hook. The Cursor app imports Claude Code plugins, so `{claude}` must
carry no Cursor file: Cursor would load the router rule and the stop hook a second time.
Cursor has no plugin dependencies, so this folder carries its own copies of the bundled
skills, the router rule, the `stackhawk.yml` rule and the stop hook.

- `skills/`: from `scripts/generate-wingman-skills.sh`, identical to `{claude}/{bundled}/`.
- Everything else: from `scripts/generate-cursor-adapter.py`, which copies the rules and the
  Cursor hooks of `plugins/hawkscan/`.

Edit the sources and run both scripts. Never list this folder in a Claude or Codex catalog.
Released builds come from `stackhawk/agent-skills-marketplace`: its `bundles/{name}/` holds
the Cursor files of this plugin next to the Copilot and Codex ones.
"""


def load_measure_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measure-cursor-context.py")
    spec = importlib.util.spec_from_file_location("measure_cursor_context", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MEASURE = load_measure_module()


def dump_json(data):
    """Same format as bump-version.sh, so a stamp never fights the generator."""
    return json.dumps(data, indent=2) + "\n"


class Tree:
    """Reads sources under one root and collects the files to write."""

    def __init__(self, root):
        self.root = root
        self.outputs = {}  # relative path -> (content bytes, executable)
        self.errors = []
        self.modes_tracked = git_tracks_modes(root)

    def path(self, rel):
        return os.path.join(self.root, rel)

    def rel(self, full):
        return os.path.relpath(full, self.root).replace(os.sep, "/")

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def json(self, rel):
        with open(self.path(rel)) as f:
            return json.load(f)

    def put(self, rel, content, executable=False):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.outputs[rel] = (data, executable)


# ─── Folders ───

def claude_folder(entry):
    """The folder a Claude catalog entry lists."""
    return entry["source"].removeprefix("./").rstrip("/")


def cursor_folder(entry):
    """The folder the Cursor catalog installs a plugin from."""
    return CURSOR_ONLY.get(entry["name"], claude_folder(entry))


def files_under(tree, rel_dir):
    """relative path inside rel_dir -> (bytes, executable) for each regular file. A symlink
    is an error: these folders are copied as they are, and a link would dangle."""
    found = {}
    base = tree.path(rel_dir)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                tree.errors.append(f"{tree.rel(full)}: a symlink; this folder holds regular files only")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                with open(full, "rb") as f:
                    found[os.path.relpath(full, base).replace(os.sep, "/")] = (f.read(), is_executable(full))
    return found


def is_executable(full):
    return bool(os.stat(full).st_mode & stat.S_IXUSR)


def git_tracks_modes(root):
    """False when git ignores the executable bit for this root (core.fileMode=false)."""
    try:
        result = subprocess.run(["git", "-C", root, "config", "--bool", "core.fileMode"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return True
    return result.stdout.strip() != "false"


# ─── Manifests and the catalog ───

def cursor_manifest(tree, entry):
    base = claude_folder(entry)
    claude = tree.json(f"{base}/.claude-plugin/plugin.json")
    codex_rel = f"{base}/.codex-plugin/plugin.json"
    codex = tree.json(codex_rel) if os.path.isfile(tree.path(codex_rel)) else {}
    if claude["name"] != entry["name"]:
        tree.errors.append(f"{base}: manifest name {claude['name']!r} differs from catalog name {entry['name']!r}")
    manifest = {"name": claude["name"]}
    target = cursor_folder(entry)
    existing_rel = f"{target}/.cursor-plugin/plugin.json"
    if os.path.isfile(tree.path(existing_rel)):
        stamped = tree.json(existing_rel).get("version")
        if stamped is not None:
            manifest["version"] = stamped
    # The Codex description is the platform-neutral one (the Claude one names Claude Code).
    manifest["description"] = codex.get("description") or claude["description"]
    author = claude.get("author", {})
    manifest["author"] = {k: author[k] for k in ("name", "email") if k in author}
    for key in ("homepage", "repository", "license", "keywords"):
        if key in claude:
            manifest[key] = claude[key]
    manifest.update(ADAPTER.get(entry["name"], {}))
    return target, manifest


def catalog(claude_catalog, manifests):
    owner = claude_catalog.get("owner", {})
    plugins = []
    for entry in claude_catalog["plugins"]:
        source = f"./{CURSOR_ONLY[entry['name']]}" if entry["name"] in CURSOR_ONLY else entry["source"]
        item = {"name": entry["name"], "source": source,
                "description": manifests[entry["name"]]["description"]}
        for key in ("category", "homepage"):
            if key in entry:
                item[key] = entry[key]
        plugins.append({k: item[k] for k in CATALOG_ENTRY_KEYS if k in item})
    return {
        "name": claude_catalog["name"],
        "owner": {k: owner[k] for k in ("name", "email") if k in owner},
        "metadata": {"description": CATALOG_DESCRIPTION},
        "plugins": plugins,
    }


def other_catalog_folders(tree):
    """Every folder the Claude and Codex catalogs list, with the catalog that lists it."""
    listed = []
    claude = tree.json(".claude-plugin/marketplace.json")
    listed += [(".claude-plugin/marketplace.json", claude_folder(e)) for e in claude["plugins"]]
    if os.path.isfile(tree.path(".codex-plugin/marketplace.json")):
        for entry in tree.json(".codex-plugin/marketplace.json")["plugins"]:
            source = entry.get("source")
            path = source.get("path") if isinstance(source, dict) else source
            listed.append((".codex-plugin/marketplace.json", str(path).removeprefix("./").rstrip("/")))
    return listed


def check_platform_boundary(tree, claude_catalog):
    """The Claude-listed folder of a Cursor-only plugin carries no Cursor file, and no Claude
    or Codex catalog lists a Cursor-only folder. Either would let Cursor load wingman's router
    rule and stop hook next to the ones of its hawkscan dependency."""
    entries = {e["name"]: e for e in claude_catalog["plugins"]}
    for name, folder in sorted(CURSOR_ONLY.items()):
        if name not in entries:
            tree.errors.append(f".claude-plugin/marketplace.json: lists no {name}; {folder} has no Claude plugin")
            continue
        base = claude_folder(entries[name])
        found = [part for part in CURSOR_PARTS if os.path.lexists(tree.path(f"{base}/{part}"))]
        for dirpath, _, names in sorted(os.walk(tree.path(base))):
            found += [tree.rel(os.path.join(dirpath, n)).removeprefix(f"{base}/") for n in sorted(names)
                      if n.endswith(".mdc")]
        for part in dict.fromkeys(found):
            tree.errors.append(f"{base}/{part}: the Claude catalog lists {base}, so it must carry no "
                               f"Cursor file; the Cursor files of {name} belong in {folder}")
        if os.path.lexists(tree.path(f"{folder}/.claude-plugin")):
            tree.errors.append(f"{folder}/.claude-plugin: a Cursor-only plugin carries no Claude manifest")
    for catalog_rel, path in other_catalog_folders(tree):
        if path == CURSOR_ONLY_ROOT or path.startswith(CURSOR_ONLY_ROOT + "/"):
            tree.errors.append(f"{catalog_rel}: lists {path}; only the Cursor catalog may list {CURSOR_ONLY_ROOT}/")


def check_bundled_skill_copies(tree, claude_catalog):
    """The skills of a Cursor-only plugin are the bundled copies of its Claude-listed folder,
    byte for byte. scripts/generate-wingman-skills.sh writes both in one run."""
    entries = {e["name"]: e for e in claude_catalog["plugins"]}
    for name, folder in sorted(CURSOR_ONLY.items()):
        if name not in entries:
            continue
        source = f"{claude_folder(entries[name])}/{BUNDLED_SKILLS}"
        target = f"{folder}/{CURSOR_ONLY_SKILLS}"
        expected = {rel: v for rel, v in files_under(tree, source).items() if rel != BUNDLED_SKILLS_README}
        found = files_under(tree, target)
        if not expected:
            tree.errors.append(f"{source}: no bundled skills; run 'bash scripts/generate-wingman-skills.sh'")
        for rel in sorted(set(expected) | set(found)):
            problem = copy_problem(found.get(rel), expected.get(rel), f"{source}/{rel}")
            if problem:
                tree.errors.append(f"{target}/{rel} ({problem}); run 'bash scripts/generate-wingman-skills.sh'")


def copy_problem(found, expected, source_rel):
    """Why a copied file is wrong, or None when it equals its source."""
    if found is None:
        return "missing"
    if expected is None:
        return "stale"
    if found[0] != expected[0]:
        crlf = found[0].replace(b"\r\n", b"\n") == expected[0].replace(b"\r\n", b"\n")
        return f"{'CRLF line endings, ' if crlf else ''}differs from {source_rel}"
    if found[1] != expected[1]:
        return f"mode differs from {source_rel}"
    return None


# ─── Rules ───

def public_skill_names(tree):
    names = set()
    for plugin in sorted(os.listdir(tree.path("plugins"))):
        skills_dir = tree.path(f"plugins/{plugin}/skills")
        if not os.path.isdir(skills_dir):
            continue
        for skill in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, skill, "SKILL.md")
            if os.path.isfile(skill_md):
                fields, _ = MEASURE.parse_frontmatter(tree.read(os.path.relpath(skill_md, tree.root)))
                names.add(fields.get("name"))
    return names


def bundle_skill_names(tree):
    bundle = tree.path(WINGMAN_BUNDLED_SKILLS)
    if not os.path.isdir(bundle):
        return set()
    return {d for d in os.listdir(bundle) if os.path.isfile(os.path.join(bundle, d, "SKILL.md"))}


def check_rules(tree):
    rules_dir = tree.path(RULES_SOURCE)
    names = sorted(n for n in os.listdir(rules_dir) if n.endswith(".mdc"))
    if not names:
        tree.errors.append(f"{RULES_SOURCE}: no rules")
    always_bytes = 0
    for name in names:
        rel = f"{RULES_SOURCE}/{name}"
        text = tree.read(rel)
        fields, body = MEASURE.parse_frontmatter(text)
        mode = MEASURE.rule_mode(fields)
        size = len(body.encode("utf-8"))
        if text.count("\n") > RULE_MAX_LINES:
            tree.errors.append(f"{rel}: {text.count(chr(10))} lines, budget {RULE_MAX_LINES}")
        if "](" in body or "references/" in body:
            tree.errors.append(f"{rel}: holds a markdown link or a references/ path; name the reference instead")
        if mode == "always":
            always_bytes += size
            check_router(tree, rel, body)
        elif mode == "glob":
            if size > GLOB_RULE_MAX_BYTES:
                tree.errors.append(f"{rel}: body is {size} bytes, budget {GLOB_RULE_MAX_BYTES}")
            for ref in re.findall(r"`([A-Za-z0-9_-]+\.md)`", body):
                if not os.path.isfile(tree.path(f"plugins/hawkscan/skills/hawkscan/references/{ref}")):
                    tree.errors.append(f"{rel}: names {ref}, which is not a hawkscan reference")
        else:
            tree.errors.append(f"{rel}: is {mode}; every rule must be alwaysApply or glob-scoped")
    if always_bytes > ROUTER_MAX_BYTES:
        tree.errors.append(f"{RULES_SOURCE}: always-applied bodies are {always_bytes} bytes, budget {ROUTER_MAX_BYTES}")
    return names


def check_router(tree, rel, body):
    named, aliases = set(), set()
    for match in re.finditer(r"^- ([a-z0-9-]+)(?: \(([a-z0-9-]+)\))?:", body, re.MULTILINE):
        named.add(match.group(1))
        if match.group(2):
            aliases.add(match.group(2))
    public = public_skill_names(tree)
    for name in sorted(named - public):
        tree.errors.append(f"{rel}: names {name}, which is not a public skill")
    for name in sorted(public - named):
        tree.errors.append(f"{rel}: does not name the public skill {name}")
    for alias in sorted(aliases - bundle_skill_names(tree)):
        tree.errors.append(f"{rel}: alias {alias} is not a wingman bundled skill")


# ─── Generate ───

def generate(tree):
    claude_catalog = tree.json(".claude-plugin/marketplace.json")
    check_platform_boundary(tree, claude_catalog)
    manifests = {}
    for entry in claude_catalog["plugins"]:
        if not os.path.isfile(tree.path(f"{claude_folder(entry)}/.claude-plugin/plugin.json")):
            tree.errors.append(f"{claude_folder(entry)}/.claude-plugin/plugin.json: missing "
                               f"(the Claude catalog lists {entry['name']})")
            return
        folder, manifest = cursor_manifest(tree, entry)
        manifests[entry["name"]] = manifest
        tree.put(f"{folder}/.cursor-plugin/plugin.json", dump_json(manifest))
    tree.put(".cursor-plugin/marketplace.json", dump_json(catalog(claude_catalog, manifests)))

    rules = check_rules(tree)
    entries = {e["name"]: e for e in claude_catalog["plugins"]}
    for name, folder in sorted(CURSOR_ONLY.items()):
        for rule in rules:
            tree.put(f"{folder}/rules/{rule}", tree.read(f"{RULES_SOURCE}/{rule}"))
        for hook in (PLUGIN_HOOKS, HOOK_SCRIPT):
            with open(tree.path(f"{HOOKS_SOURCE}/{hook}"), "rb") as f:
                tree.put(f"{folder}/hooks/cursor/{hook}", f.read(), executable=hook.endswith(".sh"))
        if name in entries:
            tree.put(f"{folder}/README.md", CURSOR_ONLY_README.format(
                name=name, claude=claude_folder(entries[name]), bundled=BUNDLED_SKILLS))
    check_bundled_skill_copies(tree, claude_catalog)


def owned_by_wingman_generator(rel):
    return any(rel.startswith(f"{folder}/{CURSOR_ONLY_SKILLS}/") for folder in CURSOR_ONLY.values())


def stale_files(tree):
    """Files under cursor-plugins/ that neither generator writes (symlinks are errors already)."""
    found = files_under(tree, CURSOR_ONLY_ROOT)
    return [f"{CURSOR_ONLY_ROOT}/{rel}" for rel in sorted(found)
            if f"{CURSOR_ONLY_ROOT}/{rel}" not in tree.outputs
            and not owned_by_wingman_generator(f"{CURSOR_ONLY_ROOT}/{rel}")]


def drift(tree):
    changed = []
    for rel, (data, executable) in sorted(tree.outputs.items()):
        full = tree.path(rel)
        if os.path.islink(full) or not os.path.isfile(full):
            changed.append(f"{rel} ({'a symlink' if os.path.islink(full) else 'missing'})")
            continue
        with open(full, "rb") as f:
            current = f.read()
        if current != data:
            crlf = current.replace(b"\r\n", b"\n") == data
            changed.append(f"{rel} ({'CRLF line endings' if crlf else 'content'})")
            continue
        if tree.modes_tracked and executable != is_executable(full):
            changed.append(f"{rel} ({'not executable' if executable else 'executable'})")
    changed += [f"{rel} (stale)" for rel in stale_files(tree)]
    return changed


def remove_empty_folders(tree, rel_dir):
    for dirpath, _, _ in sorted(os.walk(tree.path(rel_dir)), key=lambda item: -len(item[0])):
        if not os.path.islink(dirpath) and not os.listdir(dirpath):
            os.rmdir(dirpath)


def write(tree):
    for rel in stale_files(tree):
        os.remove(tree.path(rel))
        print(f"Removed: {rel}")
    for rel, (data, executable) in sorted(tree.outputs.items()):
        full = tree.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        current = None
        if os.path.isfile(full) and not os.path.islink(full):
            with open(full, "rb") as f:
                current = f.read()
        if current != data:
            if os.path.islink(full):
                os.remove(full)
            with open(full, "wb") as f:
                f.write(data)
            print(f"Generated: {rel}")
        os.chmod(full, 0o755 if executable else 0o644)
    remove_empty_folders(tree, CURSOR_ONLY_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Generate the Cursor adapter files.")
    parser.add_argument("--check", action="store_true", help="fail if a generated file is out of date; write nothing")
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="repository root (default: this checkout)")
    args = parser.parse_args()
    tree = Tree(os.path.abspath(args.root))
    generate(tree)
    files_under(tree, CURSOR_ONLY_ROOT)  # a symlink anywhere under cursor-plugins/ is an error
    if tree.errors:
        for error in dict.fromkeys(tree.errors):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.check:
        changed = drift(tree)
        if changed:
            print("ERROR: Cursor adapter files are out of date. Run 'python3 scripts/generate-cursor-adapter.py'.")
            for rel in changed:
                print(f"  {rel}")
            return 1
        print(f"OK: {len(tree.outputs)} Cursor adapter files are up to date.")
        return 0
    write(tree)
    print(f"Done. {len(tree.outputs)} Cursor adapter files are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
