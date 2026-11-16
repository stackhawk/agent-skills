#!/usr/bin/env python3
"""Export the marketplace payload of one commit.

stackhawk/agent-skills-marketplace publishes released snapshots of this repository. This
script writes, from one commit and one release version, everything the marketplace takes
from this repository:

  plugins/<name>/                  each plugin of .claude-plugin/marketplace.json, named by
                                   its catalog name, as Claude Code installs it. The umbrella
                                   wingman leaves out its Copilot and Codex bundle files
                                   (copilot-skills/, .github/). No such folder carries a Cursor
                                   rule or hook, and the Claude folders of hawkscan and wingman
                                   carry no Cursor file at all; the export refuses one. The
                                   Cursor app and the Cursor CLI import Claude Code plugins, so
                                   a second router rule and a second stop hook would load next
                                   to the native Cursor install.
  bundles/wingman/                 the wingman bundle for Copilot, Codex and Cursor, which do
                                   not install plugin dependencies: plugins/wingman with the
                                   Cursor parts (.cursor-plugin/, rules/, hooks/cursor/) of
                                   cursor-plugins/wingman, the folder that the source Cursor
                                   catalog lists. Both source folders carry the same four
                                   bundled skills; the bundle keeps one copy, copilot-skills/,
                                   and its Cursor manifest names it.
  cursor-plugins/hawkscan/         the Cursor-only hawkscan plugin, as in the source (without
                                   its README): its Cursor manifest, its skills, the rules and
                                   the Cursor hooks. The installers read the rules and the stop
                                   hook there, the same path in agent-skills and in the
                                   marketplace.
  .cursor-plugin/marketplace.json  the Cursor catalog, with marketplace sources
  install/                         install.sh, install.ps1 and cursor-legacy-rules.txt
  export-manifest.json             format 2: the commit, the version, the folder of each plugin
                                   in the Claude snapshots and in the Cursor catalog, and the
                                   mode, size and sha256 of every other file

It reads the commit with git archive (LF line endings, whatever the checkout's settings),
never the working tree. It refuses a commit whose generated files (the wingman skill copies,
the Cursor adapter) differ from what its sources give, because a direct install from the
source reads them as committed. Like the release validate job, it then stamps the version with
scripts/bump-version.sh, regenerates the wingman bundle and checks the versions, the bundle
and the Cursor adapter. Then it checks the payload with scripts/check-marketplace-layout.py,
runs the installers against it, and moves it to the destination only when every check
passes. The same commit and version always give the same bytes and modes.

The marketplace keeps what is its own: its plugin selection (sources.json), the listing URLs
and README fallbacks, the Claude, Codex and Copilot catalogs, and the standalone skills/.

--verify DIR checks an export that exists, for example before a hand sync. It fails on an
export of another commit or version, a file that is missing, changed, not listed or a symlink,
a path outside the layout, and CRLF line endings. When those pass, it exports the commit again
and compares the two manifests, so it also fails on an export that its manifest describes but
that this commit does not produce.

Usage:
  export-marketplace.py --version X.Y.Z --dest DIR [--ref REF] [--source-repo PATH]
  export-marketplace.py --verify DIR [--version X.Y.Z] [--ref REF] [--source-repo PATH]
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?")
PLUGIN_NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
MANIFEST_NAME = "export-manifest.json"
# Format 2 moved the Cursor parts of hawkscan out of plugins/hawkscan into
# cursor-plugins/hawkscan, and added the "cursor" map. A sync that reads format 1 refuses it.
FORMAT = 2
INSTALLER_DIR = "install"
INSTALLER_FILES = ("install.sh", "install.ps1", "cursor-legacy-rules.txt")

# Umbrella plugins: catalog name -> the Copilot and Codex parts that only the bundle carries.
# Claude Code reads none of them, so the Claude snapshot leaves them out.
BUNDLES = {
    "wingman": (".github", "copilot-skills"),
}
# What Cursor reads from a plugin folder beyond its skills. The bundle takes these parts from
# the umbrella's Cursor-only folder (its source in the Cursor catalog); the Claude-listed
# folder of a Cursor-only plugin must carry none of them.
CURSOR_PARTS = (".cursor-plugin", "rules", "hooks/cursor")
# Cursor rules and hooks: no Claude-listed folder carries them.
CURSOR_RULES_AND_HOOKS = ("rules", "hooks/cursor")
CURSOR_ONLY_ROOT = "cursor-plugins"
# The Cursor-only plugins that the export publishes as they are, at cursor-plugins/<name>.
# The umbrellas (BUNDLES) are Cursor-only too; their Cursor parts go into bundles/<name>.
CURSOR_ONLY_PUBLISHED = ("hawkscan",)
CURSOR_ONLY = tuple(BUNDLES) + CURSOR_ONLY_PUBLISHED
# The Cursor-only folder: its skill copies, and the README that stays in the source.
CURSOR_ONLY_SKILLS = "skills"
CURSOR_ONLY_README = "README.md"
# The skill copies that the bundle keeps, and the README they have beside them.
BUNDLED_SKILLS = "copilot-skills"
BUNDLED_SKILLS_README = "README.md"
CURSOR_MANIFEST = ".cursor-plugin/plugin.json"

# The generators of the committed files. Run on the extracted commit before the stamp, they
# must change nothing: a commit whose generated files differ from its sources is refused, not
# repaired, because a direct install from the source would read the committed files.
GENERATOR_STEPS = (
    ["bash", "scripts/generate-wingman-skills.sh"],
    [sys.executable, "scripts/generate-cursor-adapter.py"],
)

# The release validate steps, run in the extracted commit after the stamp.
STAMP_STEPS = (
    ["bash", "scripts/bump-version.sh", "{version}"],
    ["bash", "scripts/generate-wingman-skills.sh"],
    ["bash", "scripts/check-version.sh", "{version}"],
    ["bash", "scripts/test-wingman-skills.sh"],
    [sys.executable, "scripts/generate-cursor-adapter.py", "--check"],
)


class ExportError(Exception):
    """The commit cannot be exported; the message says why."""


def load_layout_check():
    path = os.path.join(SCRIPTS_DIR, "check-marketplace-layout.py")
    spec = importlib.util.spec_from_file_location("check_marketplace_layout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump_json(data):
    """The format of bump-version.sh and generate-cursor-adapter.py."""
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)
    if proc.returncode != 0:
        raise ExportError(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


# ─── Read the commit ───

def safe_member_path(name):
    path = posixpath.normpath(name)
    if path.startswith(("/", "../")) or path == "..":
        raise ExportError(f"unsafe path in the archive: {name}")
    return path


def extract(repo, commit, tree):
    # The checkout's line-ending settings must not change the bytes: archive with LF.
    data = git(repo, "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar", commit)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.name == "pax_global_header":
                continue
            rel = safe_member_path(member.name)
            target = os.path.join(tree, *rel.split("/"))
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(archive.extractfile(member).read())
                os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
            elif member.issym():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(member.linkname, target)
            else:
                raise ExportError(f"unsupported archive entry: {member.name}")
    check_symlinks(tree)


def check_symlinks(tree):
    """Every symlink, followed to its end, must stay inside the tree."""
    root = os.path.realpath(tree)
    for dirpath, dirnames, filenames in os.walk(tree):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                resolved = os.path.realpath(full)
                if resolved != root and not resolved.startswith(root + os.sep):
                    rel = os.path.relpath(full, tree)
                    raise ExportError(f"symlink leaves the tree: {rel} -> {os.readlink(full)}")


def run_steps(tree, steps, version=None):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for step in steps:
        command = [part.format(version=version) for part in step]
        proc = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise ExportError(f"{' '.join(step[1:])} failed in the exported commit:\n{proc.stdout}{proc.stderr}")


def tree_state(tree):
    """relative path -> what a generator could change: the sha256 and the executable bit of a
    file, or the target of a symlink."""
    state = {}
    for dirpath, _, filenames in os.walk(tree):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, tree).replace(os.sep, "/")
            if os.path.islink(full):
                state[rel] = ("symlink", os.readlink(full))
            else:
                with open(full, "rb") as f:
                    state[rel] = (hashlib.sha256(f.read()).hexdigest(), bool(os.stat(full).st_mode & 0o111))
    return state


def preflight(tree):
    """The commit as committed, before the stamp regenerates its copies: no Claude-listed folder
    carries a Cursor rule or hook (the one of a Cursor-only plugin no Cursor file), and the
    generators change nothing."""
    plugins = claude_plugins(tree)
    for name, source in plugins.items():
        refuse_cursor_parts(tree, name, source)
    before = tree_state(tree)
    run_steps(tree, GENERATOR_STEPS)
    after = tree_state(tree)
    changed = sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))
    if changed:
        raise ExportError("the generated files of the commit differ from what its sources give: "
                          f"{', '.join(changed[:8])}{' ...' if len(changed) > 8 else ''}. Run "
                          "'bash scripts/generate-wingman-skills.sh' and "
                          "'python3 scripts/generate-cursor-adapter.py', then commit the result")


def stamp(tree, version):
    run_steps(tree, STAMP_STEPS, version)


def read_json(tree, rel):
    try:
        with open(os.path.join(tree, *rel.split("/")), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as problem:
        raise ExportError(f"cannot read {rel}: {problem}") from problem


def claude_plugins(tree):
    """catalog name -> source folder, in catalog order."""
    plugins = {}
    for entry in read_json(tree, ".claude-plugin/marketplace.json")["plugins"]:
        if not PLUGIN_NAME_RE.fullmatch(str(entry.get("name"))) or entry["name"] in plugins:
            raise ExportError(f".claude-plugin/marketplace.json: plugin name {entry.get('name')!r} is not a new kebab-case name")
        source = entry["source"].removeprefix("./").rstrip("/")
        if not re.fullmatch(r"plugins/[a-z0-9-]+", source):
            raise ExportError(f".claude-plugin/marketplace.json: {entry['name']} has source {entry['source']}")
        plugins[entry["name"]] = source
    missing = sorted(set(CURSOR_ONLY) - set(plugins))
    if missing:
        raise ExportError(f"the Claude catalog does not list the Cursor-only plugins {missing}")
    return plugins


# ─── Build the payload ───

def omitted(rel, omits):
    return any(rel == o or rel.startswith(o + "/") for o in omits)


def folder_files(tree, source):
    """relative path -> (bytes, executable) for every file of a source folder. A symlink is
    refused: the marketplace copies these folders as they are, and a link would dangle."""
    base = os.path.join(tree, *source.split("/"))
    if not os.path.isdir(base) or os.path.islink(base):
        raise ExportError(f"the commit has no folder {source}")
    files = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                raise ExportError(f"{source}: {name} is a symlink; a plugin folder must hold regular files")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                files[os.path.relpath(full, base).replace(os.sep, "/")] = (f.read(), bool(os.stat(full).st_mode & 0o111))
    return files


def add_folder(files, tree, source, target, omits=()):
    for rel, value in folder_files(tree, source).items():
        if not omitted(rel, omits):
            files[f"{target}/{rel}"] = value


def cursor_sources(tree, plugins):
    """The source Cursor catalog, and catalog name -> the folder it installs each plugin from.
    A plugin shares its Claude-listed folder; a Cursor-only plugin (hawkscan, wingman) has its
    own folder, cursor-plugins/<name>, which the Claude catalog cannot list (its sources are
    plugins/*)."""
    catalog = read_json(tree, ".cursor-plugin/marketplace.json")
    names = [entry["name"] for entry in catalog["plugins"]]
    if names != list(plugins):
        raise ExportError(f".cursor-plugin/marketplace.json lists {names}; the Claude catalog lists {list(plugins)}")
    sources = {}
    for entry in catalog["plugins"]:
        name = entry["name"]
        expected = f"{CURSOR_ONLY_ROOT}/{name}" if name in CURSOR_ONLY else plugins[name]
        if str(entry["source"]).removeprefix("./").rstrip("/") != expected:
            raise ExportError(f".cursor-plugin/marketplace.json: {name} source {entry['source']} is not ./{expected}")
        sources[name] = expected
    return catalog, sources


def export_cursor_folder(name):
    """The folder of the export that its Cursor catalog installs a plugin from."""
    if name in BUNDLES:
        return f"bundles/{name}"
    if name in CURSOR_ONLY_PUBLISHED:
        return f"{CURSOR_ONLY_ROOT}/{name}"
    return f"plugins/{name}"


def cursor_catalog(catalog):
    """The source Cursor catalog with the marketplace folders as sources."""
    entries = [{**entry, "source": f"./{export_cursor_folder(entry['name'])}"} for entry in catalog["plugins"]]
    return dump_json({**catalog, "plugins": entries})


def refuse_cursor_parts(tree, name, source):
    """A Claude-listed folder carries no Cursor rule or hook, and the one of a Cursor-only plugin
    no Cursor part at all. The export refuses one rather than leave it out, because a direct
    Claude install from the source would load it."""
    base = os.path.join(tree, *source.split("/"))
    parts = CURSOR_PARTS if name in CURSOR_ONLY else CURSOR_RULES_AND_HOOKS
    found = [part for part in parts if os.path.lexists(os.path.join(base, *part.split("/")))]
    for dirpath, _, names in sorted(os.walk(base)):
        found += [os.path.relpath(os.path.join(dirpath, n), base).replace(os.sep, "/") for n in sorted(names)
                  if n.endswith(".mdc")]
    if found:
        home = f"{CURSOR_ONLY_ROOT}/{name}" if name in CURSOR_ONLY else "cursor-src/"
        raise ExportError(f"{source}/{found[0]}: the Claude catalog lists {source}, so it must carry no "
                          f"Cursor {'file' if name in CURSOR_ONLY else 'rule or hook'}; it belongs in {home}")


def bundle_cursor_parts(tree, name, claude_source, cursor_source):
    """The Cursor parts of an umbrella's bundle, from its Cursor-only folder. That folder holds
    only its Cursor parts, README.md and skills/, a copy of the Claude-listed copilot-skills/.
    The bundle keeps one copy of the skills, so its Cursor manifest names copilot-skills/."""
    cursor = folder_files(tree, cursor_source)
    allowed = CURSOR_PARTS + (CURSOR_ONLY_SKILLS, CURSOR_ONLY_README)
    unexpected = sorted(rel for rel in cursor if not omitted(rel, allowed))
    if unexpected:
        raise ExportError(f"{cursor_source}/{unexpected[0]}: unexpected; a Cursor-only folder holds only {', '.join(allowed)}")
    skills = {rel.split("/", 1)[1]: v for rel, v in cursor.items() if omitted(rel, (CURSOR_ONLY_SKILLS,))}
    bundled = {rel.split("/", 1)[1]: v for rel, v in folder_files(tree, claude_source).items()
               if omitted(rel, (BUNDLED_SKILLS,)) and rel != f"{BUNDLED_SKILLS}/{BUNDLED_SKILLS_README}"}
    if not skills or skills != bundled:
        raise ExportError(f"{cursor_source}/{CURSOR_ONLY_SKILLS} differs from {claude_source}/{BUNDLED_SKILLS}; "
                          "run scripts/generate-wingman-skills.sh")
    parts = {rel: v for rel, v in cursor.items() if omitted(rel, CURSOR_PARTS)}
    if CURSOR_MANIFEST not in parts:
        raise ExportError(f"{cursor_source} has no {CURSOR_MANIFEST}")
    data, executable = parts[CURSOR_MANIFEST]
    cursor_manifest = json.loads(data)
    if cursor_manifest.get("name") != name or cursor_manifest.get("skills") != f"./{CURSOR_ONLY_SKILLS}/":
        raise ExportError(f"{cursor_source}/{CURSOR_MANIFEST} must name {name} and load ./{CURSOR_ONLY_SKILLS}/")
    cursor_manifest["skills"] = f"./{BUNDLED_SKILLS}/"
    parts[CURSOR_MANIFEST] = (dump_json(cursor_manifest), executable)
    return parts


def published_cursor_folder(tree, name, claude_source, cursor_source):
    """The files of a Cursor-only plugin that the export publishes as it is: its Cursor parts
    and its skills/, a copy of the skills/ of its Claude-listed folder. Its README stays in
    the source."""
    cursor = folder_files(tree, cursor_source)
    allowed = CURSOR_PARTS + (CURSOR_ONLY_SKILLS, CURSOR_ONLY_README)
    unexpected = sorted(rel for rel in cursor if not omitted(rel, allowed))
    if unexpected:
        raise ExportError(f"{cursor_source}/{unexpected[0]}: unexpected; a Cursor-only folder holds only {', '.join(allowed)}")
    skills = {rel: v for rel, v in cursor.items() if omitted(rel, (CURSOR_ONLY_SKILLS,))}
    canonical = {rel: v for rel, v in folder_files(tree, claude_source).items() if omitted(rel, (CURSOR_ONLY_SKILLS,))}
    if not skills or skills != canonical:
        raise ExportError(f"{cursor_source}/{CURSOR_ONLY_SKILLS} differs from {claude_source}/{CURSOR_ONLY_SKILLS}; "
                          "run scripts/generate-wingman-skills.sh")
    if CURSOR_MANIFEST not in cursor:
        raise ExportError(f"{cursor_source} has no {CURSOR_MANIFEST}")
    if json.loads(cursor[CURSOR_MANIFEST][0]).get("name") != name:
        raise ExportError(f"{cursor_source}/{CURSOR_MANIFEST} must name {name}")
    return {rel: v for rel, v in cursor.items() if rel != CURSOR_ONLY_README}


def payload(tree):
    """The Claude plugins, the Cursor sources of the umbrellas, and relative path -> (bytes,
    executable) for every file of the payload but the manifest."""
    plugins = claude_plugins(tree)
    catalog, cursor = cursor_sources(tree, plugins)
    files = {}
    for name, source in plugins.items():
        refuse_cursor_parts(tree, name, source)  # preflight() refused them already; stays fail-closed
        add_folder(files, tree, source, f"plugins/{name}", BUNDLES.get(name, ()))
    for name in BUNDLES:
        add_folder(files, tree, plugins[name], f"bundles/{name}")
        for rel, value in bundle_cursor_parts(tree, name, plugins[name], cursor[name]).items():
            files[f"bundles/{name}/{rel}"] = value
    for name in CURSOR_ONLY_PUBLISHED:
        for rel, value in published_cursor_folder(tree, name, plugins[name], cursor[name]).items():
            files[f"{CURSOR_ONLY_ROOT}/{name}/{rel}"] = value
    files[".cursor-plugin/marketplace.json"] = (cursor_catalog(catalog), False)
    for name in INSTALLER_FILES:
        add_file(files, tree, f"scripts/{name}", f"{INSTALLER_DIR}/{name}")
    return plugins, {name: export_cursor_folder(name) for name in cursor}, files


def add_file(files, tree, source, target):
    full = os.path.join(tree, *source.split("/"))
    if not os.path.isfile(full) or os.path.islink(full):
        raise ExportError(f"the commit has no regular file {source}")
    with open(full, "rb") as f:
        files[target] = (f.read(), bool(os.stat(full).st_mode & 0o111))


def manifest(files, commit, version, plugins, cursor):
    """plugins maps each plugin to its Claude-listed source folder (its snapshot is
    plugins/<name>), and bundles each umbrella to the same, as sources.json does in the
    marketplace. cursor maps each plugin to the folder of the export that the Cursor catalog
    installs it from: bundles/<name> for an umbrella, cursor-plugins/<name> for another
    Cursor-only plugin, plugins/<name> for the rest."""
    return dump_json({
        "format": FORMAT,
        "source": {"commit": commit},
        "version": version,
        "plugins": plugins,
        "bundles": {name: plugins[name] for name in BUNDLES},
        "cursor": cursor,
        "files": [
            {"path": rel, "mode": "100755" if executable else "100644",
             "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for rel, (data, executable) in sorted(files.items())
        ],
    })


def write(files, root):
    """Writes every file with a fixed mode; folders get 0755 whatever the umask."""
    for rel, (data, executable) in sorted(files.items()):
        full = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        os.chmod(full, 0o755 if executable else 0o644)
    for dirpath, _, _ in os.walk(root):
        os.chmod(dirpath, 0o755)


# ─── Command line ───

def check_destination(dest):
    if os.path.lexists(dest) and not os.path.isdir(dest):
        raise ExportError(f"{dest} exists and is not a directory")
    if os.path.isdir(dest) and os.listdir(dest):
        raise ExportError(f"{dest} is not empty; give a new or empty directory")
    if not os.path.isdir(os.path.dirname(dest)):
        raise ExportError(f"the parent of {dest} does not exist")


def export(source_repo, ref, version, dest):
    """Write the payload of ref to dest. Returns the file count (without the manifest) and the commit."""
    if not VERSION_RE.fullmatch(version):
        raise ExportError(f"version {version!r} is not X.Y.Z")
    dest = os.path.abspath(dest)
    check_destination(dest)
    commit = git(source_repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    stage = tempfile.mkdtemp(prefix=".export-", dir=os.path.dirname(dest))
    try:
        with tempfile.TemporaryDirectory(prefix="agent-skills-export-") as tree:
            extract(source_repo, commit, tree)
            preflight(tree)
            stamp(tree, version)
            plugins, cursor, files = payload(tree)
        write({**files, MANIFEST_NAME: (manifest(files, commit, version, plugins, cursor), False)}, stage)
        errors = load_layout_check().check(stage, version=version, run_installers=True)
        if errors:
            raise ExportError("the payload fails the layout check:\n  " + "\n  ".join(errors))
        if os.path.isdir(dest):
            os.rmdir(dest)
        os.rename(stage, dest)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return len(files), commit


# ─── Verify an export ───

def layout_path(rel, plugins):
    """True for a path inside the export layout."""
    parts = rel.split("/")
    if rel.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return False
    if rel == ".cursor-plugin/marketplace.json" or rel in {f"{INSTALLER_DIR}/{n}" for n in INSTALLER_FILES}:
        return True
    folders = {"plugins": plugins, "bundles": BUNDLES, CURSOR_ONLY_ROOT: CURSOR_ONLY_PUBLISHED}
    return parts[0] in folders and len(parts) > 2 and parts[1] in folders[parts[0]]


def listed_files(recorded):
    """path -> entry for each file the manifest lists, and the errors of its entries."""
    listed, errors = {}, []
    plugins = recorded.get("plugins") if isinstance(recorded.get("plugins"), dict) else {}
    for item in recorded.get("files") if isinstance(recorded.get("files"), list) else []:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str) or path in listed or not layout_path(path, plugins):
            errors.append(f"{MANIFEST_NAME}: unexpected path {path!r}; it is outside the layout or listed twice")
        else:
            listed[path] = item
    return listed, errors


def file_errors(root, recorded):
    """Each file of the export must be a regular, listed, unchanged LF file, and each listed
    file must be there."""
    listed, errors = listed_files(recorded)
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                errors.append(f"{rel}: a symlink; the export holds regular files only")
            elif name in filenames and rel != MANIFEST_NAME:
                found[rel] = full
    errors += [f"{rel}: unexpected path; {MANIFEST_NAME} does not list it" for rel in sorted(set(found) - set(listed))]
    errors += [f"{rel}: missing" for rel in sorted(set(listed) - set(found))
               if not os.path.islink(os.path.join(root, *rel.split("/")))]
    for rel in sorted(set(listed) & set(found)):
        errors += entry_errors(rel, found[rel], listed[rel])
    return errors


def entry_errors(rel, full, item):
    with open(full, "rb") as f:
        data = f.read()
    errors = []
    if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
        errors.append(f"{rel}: modified; its size or sha256 differs from {MANIFEST_NAME}")
    mode = "100755" if os.stat(full).st_mode & stat.S_IXUSR else "100644"
    if mode != item.get("mode"):
        errors.append(f"{rel}: mode {mode}; {MANIFEST_NAME} lists {item.get('mode')}")
    if b"\r" in data:
        errors.append(f"{rel}: CRLF line endings; the export is LF only")
    return errors


def fresh_export_errors(source_repo, commit, version, manifest_bytes):
    """Exports the commit again and compares the manifests, which list every file's hash."""
    with tempfile.TemporaryDirectory(prefix="agent-skills-verify-") as scratch:
        fresh = os.path.join(scratch, "export")
        export(source_repo, commit, version, fresh)
        with open(os.path.join(fresh, MANIFEST_NAME), "rb") as f:
            fresh_bytes = f.read()
    if fresh_bytes == manifest_bytes:
        return []
    old = {i["path"]: i for i in json.loads(manifest_bytes)["files"]}
    new = {i["path"]: i for i in json.loads(fresh_bytes)["files"]}
    changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p)) or [MANIFEST_NAME]
    return [f"{path}: differs from a fresh export of {commit} as {version}" for path in changed]


def verify(source_repo, ref, version, root):
    """Every reason why root is not the export of ref (as version, else as its own version)."""
    root = os.path.abspath(root)
    try:
        with open(os.path.join(root, MANIFEST_NAME), "rb") as f:
            manifest_bytes = f.read()
        recorded = json.loads(manifest_bytes)
    except (OSError, ValueError) as problem:
        return [f"cannot read {MANIFEST_NAME} in {root}: {problem}"]
    if not isinstance(recorded, dict):
        return [f"{MANIFEST_NAME}: not an object"]
    commit = git(source_repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    version = version or recorded.get("version")
    errors = []
    if recorded.get("format") != FORMAT:
        errors.append(f"{MANIFEST_NAME}: unknown format {recorded.get('format')!r}")
    if (recorded.get("source") or {}).get("commit") != commit:
        errors.append(f"the export is of {(recorded.get('source') or {}).get('commit')}; {ref} is {commit}")
    if recorded.get("version") != version or not VERSION_RE.fullmatch(str(version)):
        errors.append(f"the export is version {recorded.get('version')!r}; expected {version!r}")
    errors += file_errors(root, recorded)
    return errors or fresh_export_errors(source_repo, commit, version, manifest_bytes)


def main():
    parser = argparse.ArgumentParser(description="Export the marketplace payload of one commit, or verify an export.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--dest", help="new or empty directory to write")
    target.add_argument("--verify", metavar="DIR", help="check an existing export of --ref; write nothing")
    parser.add_argument("--version", help="release version, X.Y.Z (required with --dest; with --verify, "
                                          "the export's own by default)")
    parser.add_argument("--ref", default="HEAD", help="commit, tag or branch to export (default: HEAD)")
    parser.add_argument("--source-repo", default=os.path.dirname(SCRIPTS_DIR),
                        help="agent-skills checkout to read (default: this checkout)")
    args = parser.parse_args()
    if args.dest and not args.version:
        parser.error("--dest needs --version")
    try:
        if args.verify:
            return report_verify(verify(args.source_repo, args.ref, args.version, args.verify), args.verify)
        count, commit = export(args.source_repo, args.ref, args.version, args.dest)
    except ExportError as problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"Exported {count} files of {commit} as version {args.version} to {args.dest}")
    return 0


def report_verify(errors, root):
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"FAILED: {len(errors)} problem(s) in {root}", file=sys.stderr)
        return 1
    print(f"OK: {root} is the export of its commit and version, byte for byte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
