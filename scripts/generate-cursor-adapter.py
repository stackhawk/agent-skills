#!/usr/bin/env python3
"""Generate the Cursor adapter from the canonical plugins.

Cursor reads the canonical skills (plugins/*/skills/) as Agent Skills. This script writes
only what Cursor needs beyond them, and never copies a skill body into a rule:

  plugins/<dir>/.cursor-plugin/plugin.json   one per plugin in .claude-plugin/marketplace.json
  .cursor-plugin/marketplace.json             the catalog for a Cursor team marketplace import
  plugins/wingman/rules/, hooks/cursor/       copies of hawkscan's rules and Cursor plugin hooks

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
import sys

ROUTER_MAX_BYTES = 2000
RULE_MAX_LINES = 40
GLOB_RULE_MAX_BYTES = 1200

RULES_SOURCE = "plugins/hawkscan/rules"
HOOKS_SOURCE = "plugins/hawkscan/hooks/cursor"
PLUGIN_HOOKS = "plugin-hooks.json"
HOOK_SCRIPT = "stop.sh"

# Cursor component paths per catalog plugin. Plugins not listed use Cursor's default
# skills/ folder and carry no rules or hooks. The Cursor manifest never names the
# Claude-format hooks/hooks.json, so Cursor runs its native hooks file and Claude Code
# keeps its own.
ADAPTER = {
    "hawkscan": {"rules": "./rules/", "hooks": f"./hooks/cursor/{PLUGIN_HOOKS}"},
    # Cursor has no plugin dependencies, so the umbrella bundles its skills, as for Copilot.
    "wingman": {"skills": "./copilot-skills/", "rules": "./rules/", "hooks": f"./hooks/cursor/{PLUGIN_HOOKS}"},
}
WINGMAN_DIR = "plugins/wingman"

CATALOG_DESCRIPTION = (
    "Official StackHawk plugins for Cursor. Dynamic application and API security testing "
    "(DAST) powered by HawkScan."
)
CATALOG_ENTRY_KEYS = ("name", "source", "description", "category", "homepage")


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

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def json(self, rel):
        with open(self.path(rel)) as f:
            return json.load(f)

    def put(self, rel, content, executable=False):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.outputs[rel] = (data, executable)


def cursor_manifest(tree, entry):
    base = entry["source"].removeprefix("./")
    claude = tree.json(f"{base}/.claude-plugin/plugin.json")
    codex_rel = f"{base}/.codex-plugin/plugin.json"
    codex = tree.json(codex_rel) if os.path.isfile(tree.path(codex_rel)) else {}
    if claude["name"] != entry["name"]:
        tree.errors.append(f"{base}: manifest name {claude['name']!r} differs from catalog name {entry['name']!r}")
    manifest = {"name": claude["name"]}
    existing_rel = f"{base}/.cursor-plugin/plugin.json"
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
    return base, manifest


def catalog(tree, claude_catalog, manifests):
    owner = claude_catalog.get("owner", {})
    plugins = []
    for entry in claude_catalog["plugins"]:
        item = {"name": entry["name"], "source": entry["source"],
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
    bundle = tree.path(f"{WINGMAN_DIR}/copilot-skills")
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


def generate(tree):
    claude_catalog = tree.json(".claude-plugin/marketplace.json")
    manifests = {}
    for entry in claude_catalog["plugins"]:
        base, manifest = cursor_manifest(tree, entry)
        manifests[entry["name"]] = manifest
        tree.put(f"{base}/.cursor-plugin/plugin.json", dump_json(manifest))
    tree.put(".cursor-plugin/marketplace.json", dump_json(catalog(tree, claude_catalog, manifests)))

    for name in check_rules(tree):
        tree.put(f"{WINGMAN_DIR}/rules/{name}", tree.read(f"{RULES_SOURCE}/{name}"))
    for name in (PLUGIN_HOOKS, HOOK_SCRIPT):
        with open(tree.path(f"{HOOKS_SOURCE}/{name}"), "rb") as f:
            tree.put(f"{WINGMAN_DIR}/hooks/cursor/{name}", f.read(), executable=name.endswith(".sh"))


def managed_dirs():
    """Directories whose whole content the generator owns: stale files there are removed."""
    return [f"{WINGMAN_DIR}/rules", f"{WINGMAN_DIR}/hooks/cursor"]


def stale_files(tree):
    stale = []
    for rel_dir in managed_dirs():
        full = tree.path(rel_dir)
        if os.path.isdir(full):
            for name in sorted(os.listdir(full)):
                rel = f"{rel_dir}/{name}"
                if rel not in tree.outputs:
                    stale.append(rel)
    return stale


def is_executable(full):
    return bool(os.stat(full).st_mode & stat.S_IXUSR)


def drift(tree):
    changed = []
    for rel, (data, executable) in sorted(tree.outputs.items()):
        full = tree.path(rel)
        if not os.path.isfile(full):
            changed.append(f"{rel} (missing)")
            continue
        with open(full, "rb") as f:
            if f.read() != data:
                changed.append(f"{rel} (content)")
                continue
        if executable and not is_executable(full):
            changed.append(f"{rel} (not executable)")
    changed += [f"{rel} (stale)" for rel in stale_files(tree)]
    return changed


def write(tree):
    for rel in stale_files(tree):
        os.remove(tree.path(rel))
        print(f"Removed: {rel}")
    for rel, (data, executable) in sorted(tree.outputs.items()):
        full = tree.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        current = None
        if os.path.isfile(full):
            with open(full, "rb") as f:
                current = f.read()
        if current != data:
            with open(full, "wb") as f:
                f.write(data)
            print(f"Generated: {rel}")
        if executable:
            os.chmod(full, 0o755)


def main():
    parser = argparse.ArgumentParser(description="Generate the Cursor adapter files.")
    parser.add_argument("--check", action="store_true", help="fail if a generated file is out of date; write nothing")
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="repository root (default: this checkout)")
    args = parser.parse_args()
    tree = Tree(os.path.abspath(args.root))
    generate(tree)
    if tree.errors:
        for error in tree.errors:
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
