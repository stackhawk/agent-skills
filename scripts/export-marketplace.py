#!/usr/bin/env python3
"""Export the marketplace payload of one commit.

stackhawk/agent-skills-marketplace publishes released snapshots of this repository. This
script writes, from one commit and one release version, everything the marketplace takes
from this repository:

  plugins/<name>/                  each plugin of .claude-plugin/marketplace.json, named by
                                   its catalog name, as Claude Code installs it. The umbrella
                                   wingman leaves out its bundle files (copilot-skills/,
                                   .github/, .cursor-plugin/, rules/, hooks/cursor/): Claude
                                   Code installs its dependencies, and the Cursor app imports
                                   Claude Code plugins, so a second router rule and a second
                                   stop hook would load.
  bundles/wingman/                 the complete wingman folder, for Copilot, Codex and Cursor,
                                   which do not install plugin dependencies
  .cursor-plugin/marketplace.json  the Cursor catalog, with marketplace sources
  install/                         install.sh, install.ps1 and cursor-legacy-rules.txt
  export-manifest.json             the commit, the version, and the mode, size and sha256 of
                                   every other file

It reads the commit with git archive (LF line endings, whatever the checkout's settings),
never the working tree. Like the release validate job, it stamps the version with
scripts/bump-version.sh, regenerates the wingman bundle and checks the versions, the bundle
and the Cursor adapter. Then it checks the payload with scripts/check-marketplace-layout.py,
runs the installers against it, and moves it to the destination only when every check
passes. The same commit and version always give the same bytes and modes.

The marketplace keeps what is its own: its plugin selection (sources.json), the listing URLs
and README fallbacks, the Claude, Codex and Copilot catalogs, and the standalone skills/.

Usage:
  export-marketplace.py --version X.Y.Z --dest DIR [--ref REF] [--source-repo PATH]
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
import subprocess
import sys
import tarfile
import tempfile

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?")
PLUGIN_NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
MANIFEST_NAME = "export-manifest.json"
INSTALLER_DIR = "install"
INSTALLER_FILES = ("install.sh", "install.ps1", "cursor-legacy-rules.txt")

# Umbrella plugins and the paths only their bundle carries. Claude Code reads none of these;
# Cursor would read the last three from the Claude snapshot a second time.
BUNDLES = {
    "wingman": (".github", "copilot-skills", ".cursor-plugin", "rules", "hooks/cursor"),
}

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
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if proc.returncode != 0:
        raise ExportError(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


# ─── Read the commit ───

def safe_member_path(name):
    path = posixpath.normpath(name)
    if path.startswith("/") or path == ".." or path.startswith("../"):
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


def stamp(tree, version):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for step in STAMP_STEPS:
        command = [part.format(version=version) for part in step]
        proc = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ExportError(f"{' '.join(step[1:])} failed in the exported commit:\n{proc.stdout}{proc.stderr}")


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
    missing = sorted(set(BUNDLES) - set(plugins))
    if missing:
        raise ExportError(f"the Claude catalog does not list the umbrella plugins {missing}")
    return plugins


# ─── Build the payload ───

def omitted(rel, omits):
    return any(rel == o or rel.startswith(o + "/") for o in omits)


def add_folder(files, tree, source, target, omits=()):
    base = os.path.join(tree, *source.split("/"))
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                raise ExportError(f"{source}: {name} is a symlink; a plugin folder must hold regular files")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            if not omitted(rel, omits):
                with open(full, "rb") as f:
                    files[f"{target}/{rel}"] = (f.read(), bool(os.stat(full).st_mode & 0o111))


def cursor_catalog(tree, plugins):
    catalog = read_json(tree, ".cursor-plugin/marketplace.json")
    names = [entry["name"] for entry in catalog["plugins"]]
    if names != list(plugins):
        raise ExportError(f".cursor-plugin/marketplace.json lists {names}; the Claude catalog lists {list(plugins)}")
    entries = []
    for entry in catalog["plugins"]:
        name = entry["name"]
        if entry["source"].removeprefix("./").rstrip("/") != plugins[name]:
            raise ExportError(f".cursor-plugin/marketplace.json: {name} source {entry['source']} is not {plugins[name]}")
        folder = "bundles" if name in BUNDLES else "plugins"
        entries.append({**entry, "source": f"./{folder}/{name}"})
    return dump_json({**catalog, "plugins": entries})


def payload(tree):
    """relative path -> (bytes, executable) for every file of the payload but the manifest."""
    plugins = claude_plugins(tree)
    files = {}
    for name, source in plugins.items():
        add_folder(files, tree, source, f"plugins/{name}", BUNDLES.get(name, ()))
    for name in BUNDLES:
        add_folder(files, tree, plugins[name], f"bundles/{name}")
    files[".cursor-plugin/marketplace.json"] = (cursor_catalog(tree, plugins), False)
    for name in INSTALLER_FILES:
        add_file(files, tree, f"scripts/{name}", f"{INSTALLER_DIR}/{name}")
    return plugins, files


def add_file(files, tree, source, target):
    full = os.path.join(tree, *source.split("/"))
    if not os.path.isfile(full) or os.path.islink(full):
        raise ExportError(f"the commit has no regular file {source}")
    with open(full, "rb") as f:
        files[target] = (f.read(), bool(os.stat(full).st_mode & 0o111))


def manifest(files, commit, version, plugins):
    return dump_json({
        "format": 1,
        "source": {"commit": commit},
        "version": version,
        "plugins": plugins,
        "bundles": {name: plugins[name] for name in BUNDLES},
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
            stamp(tree, version)
            plugins, files = payload(tree)
        write({**files, MANIFEST_NAME: (manifest(files, commit, version, plugins), False)}, stage)
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


def main():
    parser = argparse.ArgumentParser(description="Export the marketplace payload of one commit.")
    parser.add_argument("--version", required=True, help="release version to stamp, X.Y.Z")
    parser.add_argument("--dest", required=True, help="new or empty directory to write")
    parser.add_argument("--ref", default="HEAD", help="commit, tag or branch to export (default: HEAD)")
    parser.add_argument("--source-repo", default=os.path.dirname(SCRIPTS_DIR),
                        help="agent-skills checkout to read (default: this checkout)")
    args = parser.parse_args()
    try:
        count, commit = export(args.source_repo, args.ref, args.version, args.dest)
    except ExportError as problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"Exported {count} files of {commit} as version {args.version} to {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
