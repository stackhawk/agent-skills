"""The Cursor adapter: generated manifests, the two rules, and the plugin hooks.

Cursor reads the canonical skills as Agent Skills. The adapter adds only what Cursor needs
beyond them: a `.cursor-plugin/plugin.json` per plugin, a root `.cursor-plugin/marketplace.json`,
an always-applied router rule, a `stackhawk.yml` pointer rule, and the plugin stop hook.
`scripts/generate-cursor-adapter.py` writes the manifests and the wingman copies and checks
the rule budgets.

The schema checks mirror the plugin manifest schema in the Cursor CLI bundle
(cursor-agent 2026.06.15): only those keys, kebab-case names, `{name, email}` authors,
URL homepage and repository, and relative component paths.
"""
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATOR = os.path.join(REPO_ROOT, "scripts", "generate-cursor-adapter.py")
MEASURE = os.path.join(REPO_ROOT, "scripts", "measure-cursor-context.py")
LEGACY_LIST = os.path.join(REPO_ROOT, "scripts", "cursor-legacy-rules.txt")
ROUTER = "plugins/hawkscan/rules/stackhawk.mdc"
POINTER = "plugins/hawkscan/rules/stackhawk-config.mdc"
RULE_NAMES = ["stackhawk.mdc", "stackhawk-config.mdc"]
SHARED_PHRASE = "right after you complete a code change (feature, bugfix, refactor)"

MANIFEST_KEYS = {
    "name", "displayName", "description", "version", "author", "publisher", "homepage",
    "repository", "license", "logo", "keywords", "commands", "agents", "skills", "rules",
    "hooks", "variables", "mcpServers",
}
ENTRY_KEYS = MANIFEST_KEYS | {"source", "category", "tags", "strict"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
CANONICAL_FORBIDDEN_KEYS = {"alwaysApply", "globs", "paths", "disable-model-invocation"}


def path(rel):
    return os.path.join(REPO_ROOT, rel)


def load_json(rel):
    with open(path(rel)) as f:
        return json.load(f)


def read(rel):
    with open(path(rel)) as f:
        return f.read()


def frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "no frontmatter"
    return yaml.safe_load(match.group(1)), text[match.end():]


def catalog_plugins():
    return load_json(".claude-plugin/marketplace.json")["plugins"]


def plugin_dir(entry):
    return entry["source"].removeprefix("./")


def source_skills():
    names = {}
    for root, _dirs, files in os.walk(path("plugins")):
        if "SKILL.md" in files and os.sep + "skills" + os.sep in root + os.sep and "copilot-skills" not in root:
            fm, _ = frontmatter(read(os.path.join(root, "SKILL.md")))
            names[fm["name"]] = os.path.relpath(root, REPO_ROOT)
    return names


def wingman_bundle_names():
    return {d for d in os.listdir(path("plugins/wingman/copilot-skills")) if os.path.isdir(path(f"plugins/wingman/copilot-skills/{d}"))}


def assert_relative_component(base, value, kind):
    values = value if isinstance(value, list) else [value]
    for item in values:
        assert isinstance(item, str) and item.startswith("./"), f"{base}: {kind} path {item!r} must start with ./"
        assert ".." not in item.split("/"), f"{base}: {kind} path {item!r} must not contain .."
        target = os.path.join(path(base), item)
        assert os.path.exists(target), f"{base}: {kind} path {item!r} does not exist"


# ---------------------------------------------------------------- generator


def run_generator(*args, root=REPO_ROOT):
    return subprocess.run([sys.executable, GENERATOR, "--root", root, *args], capture_output=True, text=True)


def test_committed_output_is_current():
    proc = run_generator("--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def copy_repo(dest):
    """Copy the working tree (tracked and new files) without git metadata."""
    files = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode().split("\0")
    for rel in filter(None, files):
        src = path(rel)
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), dst)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
    return dest


def tree_digest(root):
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            h.update(os.path.relpath(full, root).encode())
            if os.path.islink(full):
                h.update(os.readlink(full).encode())
            else:
                with open(full, "rb") as f:
                    h.update(f.read())
                h.update(str(os.stat(full).st_mode & 0o111).encode())
    return h.hexdigest()


def test_generator_is_idempotent(tmp_path):
    root = copy_repo(str(tmp_path / "repo"))
    first = run_generator(root=root)
    assert first.returncode == 0, first.stderr
    before = tree_digest(root)
    second = run_generator(root=root)
    assert second.returncode == 0, second.stderr
    assert tree_digest(root) == before


def test_check_fails_on_drift(tmp_path):
    root = copy_repo(str(tmp_path / "repo"))
    target = os.path.join(root, "plugins/wingman/rules/stackhawk.mdc")
    with open(target, "a") as f:
        f.write("drift\n")
    proc = run_generator("--check", root=root)
    assert proc.returncode != 0
    assert "plugins/wingman/rules/stackhawk.mdc" in proc.stdout + proc.stderr


def test_release_stamp_round_trip(tmp_path):
    """A stamped tree passes the generator check, and --placeholder restores the tree."""
    root = copy_repo(str(tmp_path / "repo"))
    before = tree_digest(root)

    def sh(*cmd):
        proc = subprocess.run(["bash", *cmd], cwd=root, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    # The order of the validate job in release.yml.
    sh("scripts/bump-version.sh", "9.8.7")
    sh("scripts/generate-wingman-skills.sh")
    stamped = json.load(open(os.path.join(root, "plugins/hawkscan/.cursor-plugin/plugin.json")))
    assert stamped["version"] == "9.8.7"
    assert list(stamped)[:2] == ["name", "version"]
    assert run_generator("--check", root=root).returncode == 0
    sh("scripts/check-version.sh", "9.8.7")
    sh("scripts/bump-version.sh", "--placeholder")
    sh("scripts/generate-wingman-skills.sh")
    assert run_generator("--check", root=root).returncode == 0
    assert tree_digest(root) == before


def test_budget_violation_fails_the_generator(tmp_path):
    root = copy_repo(str(tmp_path / "repo"))
    with open(os.path.join(root, ROUTER), "a") as f:
        f.write("x" * 2000 + "\n")
    proc = run_generator(root=root)
    assert proc.returncode != 0
    assert "2000" in proc.stdout + proc.stderr


def test_router_naming_an_unknown_skill_fails_the_generator(tmp_path):
    root = copy_repo(str(tmp_path / "repo"))
    with open(os.path.join(root, ROUTER), "a") as f:
        f.write("- not-a-skill: nothing.\n")
    proc = run_generator(root=root)
    assert proc.returncode != 0
    assert "not-a-skill" in proc.stdout + proc.stderr


# ---------------------------------------------------------------- manifests


@pytest.mark.parametrize("entry", catalog_plugins(), ids=lambda e: e["name"])
def test_every_catalog_plugin_has_a_cursor_manifest(entry):
    base = plugin_dir(entry)
    manifest = load_json(f"{base}/.cursor-plugin/plugin.json")
    claude = load_json(f"{base}/.claude-plugin/plugin.json")
    assert manifest["name"] == entry["name"] == claude["name"]
    assert set(manifest) <= MANIFEST_KEYS, set(manifest) - MANIFEST_KEYS
    assert NAME_RE.match(manifest["name"])
    assert "version" not in manifest, "stamp_only: the release stamps the version"
    assert set(manifest["author"]) <= {"name", "email"} and manifest["author"]["name"]
    for key in ("homepage", "repository"):
        assert manifest[key].startswith("https://")
    assert all(isinstance(k, str) for k in manifest["keywords"])
    assert "Claude Code" not in manifest["description"]
    for kind in ("skills", "rules", "hooks"):
        if kind in manifest:
            assert_relative_component(base, manifest[kind], kind)
    # Never the Claude-format hooks file: Cursor would translate it instead of running ours.
    assert manifest.get("hooks") != "./hooks/hooks.json"


def test_only_hawkscan_and_wingman_carry_rules_and_hooks():
    for entry in catalog_plugins():
        manifest = load_json(f"{plugin_dir(entry)}/.cursor-plugin/plugin.json")
        carries = "rules" in manifest or "hooks" in manifest
        assert carries == (entry["name"] in {"hawkscan", "wingman"}), entry["name"]
    wingman = load_json("plugins/wingman/.cursor-plugin/plugin.json")
    assert wingman["skills"] == "./copilot-skills/"
    assert wingman["rules"] == "./rules/"
    assert wingman["hooks"] == "./hooks/cursor/plugin-hooks.json"


def test_marketplace_catalog():
    claude = load_json(".claude-plugin/marketplace.json")
    cursor = load_json(".cursor-plugin/marketplace.json")
    assert set(cursor) <= {"name", "owner", "metadata", "plugins"}
    assert cursor["name"] == claude["name"]
    assert set(cursor["owner"]) <= {"name", "email"} and cursor["owner"]["name"]
    assert [p["name"] for p in cursor["plugins"]] == [p["name"] for p in claude["plugins"]]
    for entry, claude_entry in zip(cursor["plugins"], claude["plugins"]):
        assert set(entry) <= ENTRY_KEYS
        assert entry["source"] == claude_entry["source"]
        assert "version" not in entry
        manifest = load_json(f"{plugin_dir(entry)}/.cursor-plugin/plugin.json")
        assert manifest["name"] == entry["name"]


def test_version_bump_lists_the_cursor_manifests():
    bump = load_json(".version-bump.json")
    stamp_only = {e["path"] for e in bump["files"] if e.get("stamp_only")}
    for entry in catalog_plugins():
        assert f"{plugin_dir(entry)}/.cursor-plugin/plugin.json" in stamp_only
    assert ".cursor-plugin/marketplace.json" in bump["unversioned"]


# ---------------------------------------------------------------- rules


def test_router_budget_and_mode():
    text = read(ROUTER)
    assert len(text.encode()) <= 2000
    assert text.count("\n") <= 40
    fm, _ = frontmatter(text)
    assert fm["alwaysApply"] is True
    assert "globs" not in fm


def test_router_names_every_public_skill_and_no_other():
    _, body = frontmatter(read(ROUTER))
    named, aliases = set(), set()
    for match in re.finditer(r"^- ([a-z0-9-]+)(?: \(([a-z0-9-]+)\))?:", body, re.MULTILINE):
        named.add(match.group(1))
        if match.group(2):
            aliases.add(match.group(2))
    assert named == set(source_skills())
    assert aliases <= wingman_bundle_names()


def test_router_and_hawkscan_description_share_the_autonomy_phrase():
    flat = lambda s: " ".join(s.split())  # noqa: E731
    assert SHARED_PHRASE in flat(read(ROUTER))
    fm, _ = frontmatter(read("plugins/hawkscan/skills/hawkscan/SKILL.md"))
    assert SHARED_PHRASE in flat(fm["description"])


def test_pointer_budget_mode_and_references():
    text = read(POINTER)
    assert len(text.encode()) <= 1200
    fm, body = frontmatter(text)
    assert fm["alwaysApply"] is False
    assert fm["globs"] == ["**/stackhawk.yml", "**/stackhawk-*.yml"]
    for name in re.findall(r"`([a-z0-9-]+\.md)`", body):
        assert os.path.isfile(path(f"plugins/hawkscan/skills/hawkscan/references/{name}")), name


def test_rules_have_no_links_or_reference_paths():
    for plugin in ("hawkscan", "wingman"):
        rules = sorted(os.listdir(path(f"plugins/{plugin}/rules")))
        assert rules == sorted(RULE_NAMES)
        for name in rules:
            text = read(f"plugins/{plugin}/rules/{name}")
            assert "](" not in text, f"{plugin}/{name} has a markdown link"
            assert "references/" not in text, f"{plugin}/{name} names a path that does not resolve"


def test_wingman_copies_are_identical():
    pairs = [(f"plugins/hawkscan/rules/{n}", f"plugins/wingman/rules/{n}") for n in RULE_NAMES] + [
        ("plugins/hawkscan/hooks/cursor/stop.sh", "plugins/wingman/hooks/cursor/stop.sh"),
        ("plugins/hawkscan/hooks/cursor/plugin-hooks.json", "plugins/wingman/hooks/cursor/plugin-hooks.json"),
    ]
    for src, dst in pairs:
        assert filecmp.cmp(path(src), path(dst), shallow=False), dst


def test_wingman_never_gets_claude_hooks_or_skills():
    assert not os.path.exists(path("plugins/wingman/hooks/hooks.json"))
    assert not os.path.exists(path("plugins/wingman/skills"))
    assert sorted(os.listdir(path("plugins/wingman/hooks"))) == ["cursor"]


@pytest.mark.parametrize("rel", ["plugins/hawkscan/hooks/cursor/stop.sh", "plugins/wingman/hooks/cursor/stop.sh"])
def test_hook_scripts_are_executable_in_git(rel):
    assert os.access(path(rel), os.X_OK)
    staged = subprocess.run(["git", "ls-files", "-s", rel], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    if staged:
        assert staged.startswith("100755"), staged


@pytest.mark.parametrize("name", sorted(source_skills()))
def test_canonical_skills_carry_no_cursor_keys(name):
    fm, _ = frontmatter(read(f"{source_skills()[name]}/SKILL.md"))
    assert not CANONICAL_FORBIDDEN_KEYS & set(fm), f"{name} carries {CANONICAL_FORBIDDEN_KEYS & set(fm)}"


# ---------------------------------------------------------------- legacy rules


def test_legacy_rule_list_covers_the_deprecated_generator():
    """Installers delete exactly these names; the list must outlive cursor/ itself.

    It holds every name the old generator ever wrote (45, from git history), not only the
    28 it writes today: an install from an older release still carries the others.
    """
    with open(LEGACY_LIST) as f:
        listed = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    assert len(listed) == len(set(listed)) == 45
    generated = re.findall(r'^\s+"[^|]+\|([a-z0-9-]+)\|', read("scripts/generate-cursor-rules.sh"), re.MULTILINE)
    assert {f"{n}.mdc" for n in generated} <= set(listed)
    assert set(os.listdir(path("cursor/.cursor/rules"))) <= set(listed)
    assert all(re.fullmatch(r"stackhawk-[a-z0-9-]+\.mdc", name) for name in listed)
    assert not set(listed) & set(RULE_NAMES)


# ---------------------------------------------------------------- measurement


def test_plugin_layout_meets_the_context_budgets():
    proc = subprocess.run(
        [sys.executable, MEASURE, "--check", "--json", path("plugins/hawkscan")], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["always_applied_bytes"] <= 2000
    assert report["attach_bytes"]["stackhawk.yml"] <= 1500
    assert report["dangling_rule_links"] == 0
