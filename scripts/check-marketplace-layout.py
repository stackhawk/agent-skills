#!/usr/bin/env python3
"""Check a marketplace tree before it is published.

The release runs this on the payload that scripts/export-marketplace.py writes and on the
synced stackhawk/agent-skills-marketplace checkout, before the push. It fails when:

  - an install makes Cursor load more than one always-applied (router) rule, more than one
    stop hook, or one rule file or skill twice. It counts each plugin of the Cursor catalog
    installed alone, and each Claude Code install (a plugin with its dependencies, and every
    plugin together) that Cursor imports. The Cursor app imports Claude Code plugins by
    default (importPluginsFromClaudeOnBoot), and which manifest it reads for them is not
    documented, so a Claude Code install is counted with each manifest. A component path
    that a manifest names replaces the default folder (rules/, hooks/hooks.json, skills/);
    without one, the default folder counts.
  - a Cursor install that carries the hawkscan skill lacks its router rule or its stop hook,
    or a Cursor install loads no skill;
  - a file of the Cursor distribution is missing: the Cursor catalog, a plugin's Cursor
    manifest or a path it names, a hook script, the installers or the legacy rule list;
  - the Claude Code packaging is broken: a manifest name differs from its catalog name, a
    dependency is not in the catalog, an umbrella plugin carries skills/ (Claude Code would
    load its skills twice), a component plugin has no skill, or a Claude hook names a script
    that is missing or not executable;
  - with --version, a Cursor manifest or a SKILL.md carries another version;
  - with --run-installers, install.sh (and install.ps1 when pwsh is installed) cannot make a
    Cursor project install from the tree: every skill, both rules, the stop hook and one
    hooks.json stop entry.

The Claude plugins are the entries of .claude-plugin/marketplace.json; a tree without that
catalog (the export) lists them as the plugins/*/ folders.

What the counts assume about Cursor, from its documentation and the code of its 3.9.16 app
and 2026.11.11 CLI, not from a live run of every case:
  - a component path that a manifest names replaces the default folder of that component;
  - any alwaysApply value that is not clearly false (false, no, off, 0) makes a router rule.
It does not count installs that combine channels or catalog entries: hawkscan and wingman
from the Cursor catalog, or a Cursor catalog install next to an imported Claude Code
install. Each loads the router twice; the README tells users to pick one.

Usage:
  check-marketplace-layout.py [--version X.Y.Z] [--no-installers] [--run-installers] ROOT
"""
import argparse
import collections
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROUTER_SKILL = "hawkscan"
RULE_SUFFIXES = (".mdc", ".md", ".markdown")
INSTALLER_DIR = "install"
INSTALLER_FILES = ("install.sh", "install.ps1", "cursor-legacy-rules.txt")
CURSOR_MANIFEST = ".cursor-plugin/plugin.json"
CLAUDE_MANIFEST = ".claude-plugin/plugin.json"
CURSOR_ROOT_VAR = "${CURSOR_PLUGIN_ROOT}"
CLAUDE_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
FALSE_VALUES = {"false", "no", "off", "0", ""}
INSTALLED_RULES = ("stackhawk.mdc", "stackhawk-config.mdc")
INSTALLED_HOOK = "hooks/stackhawk-stop.sh"


def load_measure_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measure-cursor-context.py")
    spec = importlib.util.spec_from_file_location("measure_cursor_context", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MEASURE = load_measure_module()

Rule = collections.namedtuple("Rule", "path always")
Hook = collections.namedtuple("Hook", "path command")
Skill = collections.namedtuple("Skill", "name path")
Loaded = collections.namedtuple("Loaded", "folder manifest rules stop_hooks skills")


class Layout:
    """One tree under check: reads its files and collects errors, each reported once."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.errors = []
        self._loaded = {}

    def error(self, message):
        if message not in self.errors:
            self.errors.append(message)

    def full(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def rel(self, full):
        return os.path.relpath(full, self.root).replace(os.sep, "/")

    def read_json(self, rel):
        try:
            with open(self.full(rel), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            self.error(f"missing {rel}")
        except (OSError, ValueError) as problem:
            self.error(f"{rel}: not valid JSON ({problem})")
        return None

    def frontmatter(self, full):
        with open(full, encoding="utf-8") as f:
            fields, _ = MEASURE.parse_frontmatter(f.read())
        return fields


def folder_of(source):
    """The folder a catalog source names, relative to the root; None if it leaves the root."""
    path = source.get("path") if isinstance(source, dict) else source
    if not isinstance(path, str):
        return None
    path = path.removeprefix("./").rstrip("/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        return None
    return path


def component_paths(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def is_executable(full):
    return os.path.isfile(full) and os.access(full, os.X_OK)


def always_applied(value):
    """True unless alwaysApply is absent or clearly false. The frontmatter parser reads only a
    bare `true` as true; `True`, `"true"` or `true # comment` are true for a YAML reader, and a
    second router must not pass because of how it is spelled."""
    if value is None or value is False:
        return False
    if value is True:
        return True
    return str(value).split(" #")[0].strip().strip("'\"").strip().lower() not in FALSE_VALUES


# ─── How Cursor loads one plugin folder ───

def component_files(layout, folder, manifest_rel, manifest, key, default):
    """Files of one component: the paths the manifest names, else the default folder or file."""
    if key not in manifest:
        full = layout.full(f"{folder}/{default}")
        return [full] if os.path.exists(full) else []
    paths = component_paths(manifest[key])
    if paths is None:
        layout.error(f"{folder}/{manifest_rel}: {key} must be a path or a list of paths")
        return []
    found = []
    for path in paths:
        sub = folder_of(path)
        full = layout.full(f"{folder}/{sub}") if sub else None
        if not full or not os.path.exists(full):
            layout.error(f"{folder}/{manifest_rel}: {key} path {path} does not exist")
        else:
            found.append(full)
    return found


def rule_files(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            for dirpath, _, names in sorted(os.walk(path)):
                files += [os.path.join(dirpath, n) for n in sorted(names) if n.endswith(RULE_SUFFIXES)]
        else:
            files.append(path)
    return files


def stop_hooks(layout, hook_files):
    hooks = []
    for full in hook_files:
        data = layout.read_json(layout.rel(full)) if os.path.isfile(full) else None
        events = data.get("hooks", {}) if isinstance(data, dict) else {}
        for item in events.get("stop", []) if isinstance(events, dict) else []:
            hooks.append(Hook(layout.rel(full), str(item.get("command", "")) if isinstance(item, dict) else ""))
        for group in events.get("Stop", []) if isinstance(events, dict) else []:
            for item in group.get("hooks", []) if isinstance(group, dict) else []:
                hooks.append(Hook(layout.rel(full), str(item.get("command", ""))))
    return hooks


def skills_in(layout, paths):
    skills = []
    for path in paths:
        if not os.path.isdir(path):
            continue
        for name in sorted(os.listdir(path)):
            skill_md = os.path.join(path, name, "SKILL.md")
            if os.path.isfile(skill_md):
                skills.append(Skill(layout.frontmatter(skill_md).get("name") or name, layout.rel(skill_md)))
    return skills


def load_plugin(layout, folder, prefer_cursor):
    """The rules, stop hooks and skills Cursor takes from a folder. With prefer_cursor, Cursor
    reads the Cursor manifest when there is one, as its CLI does; otherwise the Claude one."""
    key = (folder, prefer_cursor)
    if key not in layout._loaded:
        manifest_rel = CURSOR_MANIFEST
        if not (prefer_cursor and os.path.isfile(layout.full(f"{folder}/{CURSOR_MANIFEST}"))):
            manifest_rel = CLAUDE_MANIFEST
        manifest = layout.read_json(f"{folder}/{manifest_rel}") or {}
        rules = [Rule(layout.rel(f), always_applied(layout.frontmatter(f).get("alwaysApply")))
                 for f in rule_files(component_files(layout, folder, manifest_rel, manifest, "rules", "rules"))]
        hooks = stop_hooks(layout, component_files(layout, folder, manifest_rel, manifest, "hooks", "hooks/hooks.json"))
        skills = skills_in(layout, component_files(layout, folder, manifest_rel, manifest, "skills", "skills"))
        layout._loaded[key] = Loaded(folder, manifest_rel, rules, hooks, skills)
    return layout._loaded[key]


def check_scenario(layout, label, plugins):
    """Errors for one install: at most one router rule and one stop hook, nothing loaded twice."""
    routers = [r.path for p in plugins for r in p.rules if r.always]
    hooks = [h.path for p in plugins for h in p.stop_hooks]
    if len(routers) > 1:
        layout.error(f"{label}: {len(routers)} router rules ({', '.join(routers)}); "
                     "Cursor must load at most one always-applied rule")
    if len(hooks) > 1:
        layout.error(f"{label}: {len(hooks)} stop hooks ({', '.join(hooks)}); at most one may run")
    rule_names = collections.Counter(os.path.basename(r.path) for p in plugins for r in p.rules)
    skill_names = collections.Counter(s.name for p in plugins for s in p.skills)
    for kind, counts in (("rule", rule_names), ("skill", skill_names)):
        for name, count in sorted(counts.items()):
            if count > 1:
                layout.error(f"{label}: {kind} {name} loads {count} times")
    return routers, hooks, set(skill_names)


# ─── The Cursor catalog ───

def check_plugin_hook_commands(layout, plugin):
    for hook in plugin.stop_hooks:
        command = hook.command.strip()
        script = command.split('"')[1] if command.startswith('"') else command.split(" ")[0]
        if not script.startswith(CURSOR_ROOT_VAR + "/"):
            layout.error(f"{hook.path}: stop command {command} does not start with {CURSOR_ROOT_VAR}; "
                         "Cursor runs plugin stop hooks from the workspace root")
            continue
        target = f"{plugin.folder}/{script[len(CURSOR_ROOT_VAR) + 1:]}"
        if not is_executable(layout.full(target)):
            layout.error(f"{hook.path}: stop command names {target}, which is missing or not executable")


def check_cursor_catalog(layout, claude_names):
    catalog = layout.read_json(".cursor-plugin/marketplace.json")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("plugins"), list):
        if catalog is not None:
            layout.error(".cursor-plugin/marketplace.json: no plugins list")
        return []
    folders = []
    for entry in catalog["plugins"]:
        name, folder = entry.get("name"), folder_of(entry.get("source"))
        if folder is None:
            layout.error(f".cursor-plugin/marketplace.json: {name} has a source outside the tree")
            continue
        if not os.path.isfile(layout.full(f"{folder}/{CURSOR_MANIFEST}")):
            layout.error(f"missing {folder}/{CURSOR_MANIFEST} (Cursor catalog entry {name})")
            continue
        folders.append(folder)
        check_cursor_install(layout, name, folder)
    names = {entry.get("name") for entry in catalog["plugins"]}
    if claude_names is not None and names != set(claude_names):
        layout.error(f".cursor-plugin/marketplace.json lists {sorted(names)}; the Claude plugins are {sorted(claude_names)}")
    return folders


def check_cursor_install(layout, name, folder):
    plugin = load_plugin(layout, folder, prefer_cursor=True)
    manifest = layout.read_json(f"{folder}/{CURSOR_MANIFEST}") or {}
    if manifest.get("name") != name:
        layout.error(f"{folder}/{CURSOR_MANIFEST}: name {manifest.get('name')!r} differs from catalog name {name!r}")
    label = f"Cursor install of {name} ({folder})"
    routers, hooks, skills = check_scenario(layout, label, [plugin])
    if not skills:
        layout.error(f"{label}: loads no skill")
    if ROUTER_SKILL in skills and (len(routers) != 1 or len(hooks) != 1):
        layout.error(f"{label}: carries the {ROUTER_SKILL} skill with {len(routers)} router rules and "
                     f"{len(hooks)} stop hooks; expected exactly one of each")
    check_plugin_hook_commands(layout, plugin)


# ─── The Claude plugins ───

def claude_plugins(layout):
    """name -> folder for every plugin Claude Code installs from this tree."""
    catalog_rel = ".claude-plugin/marketplace.json"
    if os.path.isfile(layout.full(catalog_rel)):
        catalog = layout.read_json(catalog_rel) or {}
        plugins = {}
        for entry in catalog.get("plugins", []):
            folder = folder_of(entry.get("source"))
            if folder is None:
                layout.error(f"{catalog_rel}: {entry.get('name')} has a source outside the tree")
            else:
                plugins[entry.get("name")] = folder
        return plugins
    plugins = {}
    base = layout.full("plugins")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if os.path.isfile(os.path.join(base, name, *CLAUDE_MANIFEST.split("/"))):
            manifest = layout.read_json(f"plugins/{name}/{CLAUDE_MANIFEST}") or {}
            plugins[manifest.get("name", name)] = f"plugins/{name}"
    return plugins


def check_claude_hook_scripts(layout, folder):
    rel = f"{folder}/hooks/hooks.json"
    if not os.path.isfile(layout.full(rel)):
        return
    data = layout.read_json(rel) or {}
    for groups in (data.get("hooks") or {}).values():
        for group in groups if isinstance(groups, list) else []:
            for item in group.get("hooks", []) if isinstance(group, dict) else []:
                check_claude_command(layout, rel, folder, str(item.get("command", "")))


def check_claude_command(layout, rel, folder, command):
    parts = command.replace('"', " ").split()
    if not parts or not parts[0].startswith(CLAUDE_ROOT_VAR + "/"):
        return
    script = f"{folder}/{parts[0][len(CLAUDE_ROOT_VAR) + 1:]}"
    targets = [script]
    if os.path.basename(script) == "run-hook.cmd" and len(parts) > 1:
        targets.append(f"{os.path.dirname(script)}/{parts[1]}")
    for target in targets:
        if not is_executable(layout.full(target)):
            layout.error(f"{rel}: a Claude hook runs {target}, which is missing or not executable")


def check_claude_plugin(layout, name, folder, plugins):
    manifest = layout.read_json(f"{folder}/{CLAUDE_MANIFEST}") or {}
    if manifest.get("name") != name:
        layout.error(f"{folder}/{CLAUDE_MANIFEST}: name {manifest.get('name')!r} differs from catalog name {name!r}")
    dependencies = manifest.get("dependencies") or []
    for dependency in dependencies:
        if dependency not in plugins:
            layout.error(f"{folder}/{CLAUDE_MANIFEST}: dependency {dependency} is not a Claude plugin in this tree")
    if dependencies and os.path.exists(layout.full(f"{folder}/skills")):
        layout.error(f"{folder}: an umbrella plugin carries skills/; Claude Code would load its dependencies' skills twice")
    if not dependencies and not skills_in(layout, [layout.full(f"{folder}/skills")]):
        layout.error(f"{folder}: a Claude plugin without dependencies has no skills/*/SKILL.md")
    check_claude_hook_scripts(layout, folder)
    return dependencies


def closure(name, dependencies):
    seen, stack = [], [name]
    while stack:
        current = stack.pop()
        if current in seen or current not in dependencies:
            continue
        seen.append(current)
        stack.extend(reversed(dependencies[current]))
    return seen


def check_claude_imports(layout, plugins):
    dependencies = {name: check_claude_plugin(layout, name, folder, plugins) for name, folder in plugins.items()}
    installs = [(name, closure(name, dependencies)) for name in plugins]
    if len(plugins) > 1:
        installs.append(("every plugin", list(plugins)))
    for prefer_cursor, reads in ((True, f"{CURSOR_MANIFEST} when present"), (False, CLAUDE_MANIFEST)):
        for name, members in installs:
            label = f"Claude Code install of {name} imported into Cursor (Cursor reads {reads})"
            check_scenario(layout, label, [load_plugin(layout, plugins[m], prefer_cursor) for m in members])


# ─── Installers and versions ───

def check_installers(layout):
    for name in INSTALLER_FILES:
        rel = f"{INSTALLER_DIR}/{name}"
        full = layout.full(rel)
        if not os.path.isfile(full):
            layout.error(f"missing {rel}")
        elif name.endswith(".sh") and not is_executable(full):
            layout.error(f"{rel}: not executable")
    legacy = layout.full(f"{INSTALLER_DIR}/cursor-legacy-rules.txt")
    if os.path.isfile(legacy):
        with open(legacy, encoding="utf-8") as f:
            if not [line for line in f if line.strip() and not line.startswith("#")]:
                layout.error(f"{INSTALLER_DIR}/cursor-legacy-rules.txt: lists no rule")


def installer_commands(layout):
    """(installer, command without its target folder) for each installer in the tree; install.ps1
    only when pwsh is installed."""
    sh, ps1 = layout.full(f"{INSTALLER_DIR}/install.sh"), layout.full(f"{INSTALLER_DIR}/install.ps1")
    commands = []
    if os.path.isfile(sh):
        commands.append(("install.sh", ["bash", sh, "--platform", "cursor", "--target"]))
    if os.path.isfile(ps1) and shutil.which("pwsh"):
        commands.append(("install.ps1", ["pwsh", "-NoProfile", "-NonInteractive", "-File", ps1,
                                         "-Platform", "cursor", "-Target"]))
    return commands


def same_file(a, b):
    with open(a, "rb") as f, open(b, "rb") as g:
        return f.read() == g.read()


def plugin_skill_folders(layout):
    folders = {}
    for plugin in sorted(os.listdir(layout.full("plugins"))) if os.path.isdir(layout.full("plugins")) else []:
        skills = layout.full(f"plugins/{plugin}/skills")
        for name in sorted(os.listdir(skills)) if os.path.isdir(skills) else []:
            folders.setdefault(name, []).append(os.path.join(skills, name))
    return folders


def tree_files(root):
    found = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                found[os.path.relpath(full, root)] = f.read()
    return found


def check_installed(layout, label, dot_cursor):
    """What a Cursor project install from this tree must hold."""
    rules = layout.full("plugins/hawkscan/rules")
    for name in INSTALLED_RULES:
        installed = os.path.join(dot_cursor, "rules", name)
        if not os.path.isfile(installed) or not same_file(installed, os.path.join(rules, name)):
            layout.error(f"{label}: the install has no rules/{name} from plugins/hawkscan/rules/")
    hook = os.path.join(dot_cursor, *INSTALLED_HOOK.split("/"))
    if not is_executable(hook) or not same_file(hook, layout.full("plugins/hawkscan/hooks/cursor/stop.sh")):
        layout.error(f"{label}: the install has no executable {INSTALLED_HOOK} from plugins/hawkscan/hooks/cursor/")
    try:
        with open(os.path.join(dot_cursor, "hooks.json"), encoding="utf-8") as f:
            stops = json.load(f)["hooks"]["stop"]
    except (OSError, ValueError, KeyError, TypeError):
        stops = []
    if len(stops) != 1:
        layout.error(f"{label}: the install's hooks.json has {len(stops)} stop entries, expected one")
    installed = sorted(os.listdir(os.path.join(dot_cursor, "skills"))) if os.path.isdir(os.path.join(dot_cursor, "skills")) else []
    if not installed:
        layout.error(f"{label}: the install has no skill")
    sources = plugin_skill_folders(layout)
    for name in installed:
        files = tree_files(os.path.join(dot_cursor, "skills", name))
        if not any(tree_files(source) == files for source in sources.get(name, [])):
            layout.error(f"{label}: the installed skill {name} is not a copy of plugins/*/skills/{name}")


def check_installers_run(layout):
    """Runs each installer into a scratch project with a scratch HOME and checks the result."""
    for name, command in installer_commands(layout):
        label = f"{INSTALLER_DIR}/{name}"
        with tempfile.TemporaryDirectory(prefix="check-install-") as scratch:
            home, project = os.path.join(scratch, "home"), os.path.join(scratch, "project")
            os.makedirs(home)
            os.makedirs(project)
            env = {k: v for k, v in os.environ.items() if not k.startswith("CURSOR_")}
            env["HOME"] = home
            proc = subprocess.run(command + [project], env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                output = " ".join((proc.stderr or proc.stdout).split())
                layout.error(f"{label}: a Cursor project install from this tree failed: {output}")
            else:
                check_installed(layout, label, os.path.join(project, ".cursor"))


def check_versions(layout, version, folders):
    for folder in sorted(set(folders)):
        manifest_rel = f"{folder}/{CURSOR_MANIFEST}"
        if os.path.isfile(layout.full(manifest_rel)):
            found = (layout.read_json(manifest_rel) or {}).get("version")
            if found != version:
                layout.error(f"{manifest_rel}: version {found!r}, expected {version}")
        for dirpath, _, names in sorted(os.walk(layout.full(folder))):
            if "SKILL.md" in names:
                full = os.path.join(dirpath, "SKILL.md")
                found = layout.frontmatter(full).get("version")
                if found != version:
                    layout.error(f"{layout.rel(full)}: version {found!r}, expected {version}")


def check(root, version=None, require_installers=True, run_installers=False):
    """Every error found in the tree at root; an empty list means it may be published."""
    layout = Layout(root)
    plugins = claude_plugins(layout)
    if not plugins:
        layout.error("no Claude plugins: neither .claude-plugin/marketplace.json nor plugins/*/.claude-plugin/plugin.json")
    cursor_folders = check_cursor_catalog(layout, plugins or None)
    check_claude_imports(layout, plugins)
    if require_installers:
        check_installers(layout)
    if run_installers:
        check_installers_run(layout)
    if version is not None:
        check_versions(layout, version, cursor_folders + list(plugins.values()))
    return layout.errors


def main():
    parser = argparse.ArgumentParser(description="Check a marketplace tree before it is published.")
    parser.add_argument("root", help="the export or the marketplace checkout")
    parser.add_argument("--version", help="the release version every Cursor manifest and SKILL.md must carry")
    parser.add_argument("--no-installers", action="store_true", help="do not require install/ (a source checkout)")
    parser.add_argument("--run-installers", action="store_true",
                        help="also run install/install.sh (and install.ps1 with pwsh) into a scratch project")
    args = parser.parse_args()
    if not os.path.isdir(args.root):
        print(f"ERROR: {args.root} is not a directory", file=sys.stderr)
        return 1
    errors = check(args.root, version=args.version, require_installers=not args.no_installers,
                   run_installers=args.run_installers)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"FAILED: {len(errors)} problem(s) in {args.root}", file=sys.stderr)
        return 1
    print(f"OK: {args.root}: at most one router rule and one stop hook in each checked install, "
          "and every Cursor distribution file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
