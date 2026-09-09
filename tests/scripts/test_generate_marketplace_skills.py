"""Tests for scripts/generate-marketplace-skills.py (vendors skills into the marketplace repo)."""
import hashlib
import importlib.util
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "generate-marketplace-skills.py")
CATALOGS = os.path.join(REPO_ROOT, "scripts", "generate-marketplace-catalogs.py")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


catalogs = load_module(CATALOGS, "gen_catalogs")
EXPECTED = sorted(p for p in catalogs.DEFAULT_PLUGINS if p != "wingman")


def run(out_dir, *extra):
    return subprocess.run(
        [sys.executable, SCRIPT, "--out-dir", str(out_dir), *extra],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def first_name_line(path):
    with open(path) as f:
        return next(line.rstrip("\n") for line in f if line.startswith("name:"))


def tree_digest(root):
    """Content+path digest of a tree, following symlinks (used to prove sources are untouched)."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


@pytest.fixture
def generated(tmp_path):
    src_before = tree_digest(os.path.join(REPO_ROOT, "plugins"))
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert tree_digest(os.path.join(REPO_ROOT, "plugins")) == src_before
    return tmp_path / "skills", result


def test_default_run_produces_exactly_non_wingman_plugins(generated):
    skills, _ = generated
    dirs = sorted(p.name for p in skills.iterdir() if p.is_dir())
    assert dirs == EXPECTED
    assert len(dirs) == 5
    assert "wingman" not in dirs
    for d in dirs:
        assert (skills / d / "SKILL.md").read_text().startswith("---")


def test_output_contains_no_symlinks(generated):
    skills, _ = generated
    for dirpath, dirnames, filenames in os.walk(skills):
        for n in dirnames + filenames:
            assert not os.path.islink(os.path.join(dirpath, n)), os.path.join(dirpath, n)


def test_lockstep_with_default_plugins(generated):
    skills, _ = generated
    for name in EXPECTED:
        assert (skills / name / "SKILL.md").is_file(), name


def test_name_rewrite_only_where_it_differs(generated):
    skills, out = generated
    assert first_name_line(skills / "stackhawk-api" / "SKILL.md") == "name: stackhawk-api"
    assert first_name_line(skills / "stackhawk-optimize" / "SKILL.md") == "name: stackhawk-optimize"
    assert first_name_line(skills / "hawkscan" / "SKILL.md") == "name: hawkscan"
    assert first_name_line(os.path.join(REPO_ROOT, "skills", "stackhawk-api", "SKILL.md")) == "name: api"
    assert "api -> stackhawk-api" in out.stdout


def test_stale_file_removed_on_rebuild(tmp_path):
    stale = tmp_path / "skills" / "old-skill" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("---\nname: old\n---\n")
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not stale.parent.exists()


def test_readme_written(generated):
    skills, _ = generated
    text = (skills / "README.md").read_text()
    assert "GENERATED" in text
    assert "generate-marketplace-skills.py" in text
    assert "plugins/*/skills/*/" in text


def test_plugins_all_excludes_wingman(tmp_path):
    result = run(tmp_path, "--plugins", "all")
    assert result.returncode == 0, result.stderr
    dirs = sorted(p.name for p in (tmp_path / "skills").iterdir() if p.is_dir())
    assert dirs == EXPECTED


def test_unknown_plugin_fails_before_deleting(tmp_path):
    existing = tmp_path / "skills" / "keep" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("x")
    result = run(tmp_path, "--plugins", "hawkscan,does-not-exist")
    assert result.returncode != 0
    assert "does-not-exist" in result.stderr
    assert existing.exists()


def test_explicit_wingman_is_rejected(tmp_path):
    result = run(tmp_path, "--plugins", "wingman")
    assert result.returncode != 0
    assert "wingman" in result.stderr


def test_no_skill_authoring_dir_in_output(generated):
    skills, _ = generated
    for dirpath, dirnames, _ in os.walk(skills):
        assert "skill-authoring" not in dirnames, dirpath


def test_summary_line_printed(generated):
    _, out = generated
    assert "5 skill(s)" in out.stdout
