"""scripts/test-wingman-skills.sh: the check of the bundled wingman skill copies and of the
skills of the Cursor-only hawkscan plugin.

CI and the release validate job run the script after generate-wingman-skills.sh. Each test
damages a copy of this working tree and expects the script to fail with a named error; the
undamaged copy passes. The script finds the tree from its own location.
"""
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COPILOT = "plugins/wingman/copilot-skills"
CURSOR = "cursor-plugins/wingman/skills"
HAWKSCAN = "plugins/hawkscan/skills"
CURSOR_HAWKSCAN = "cursor-plugins/hawkscan/skills"


def copy_tree(dest):
    """Copy the working tree (tracked and new files) without git metadata."""
    files = subprocess.run(["git", "-C", REPO_ROOT, "ls-files", "-co", "--exclude-standard", "-z"],
                           capture_output=True, check=True).stdout.decode().split("\0")
    for rel in filter(None, files):
        src = os.path.join(REPO_ROOT, rel)
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), dst)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
    return dest


def run_check(root):
    proc = subprocess.run(["bash", os.path.join(root, "scripts", "test-wingman-skills.sh")],
                          capture_output=True, text=True, timeout=120, check=False)
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture
def tree(tmp_path):
    return copy_tree(str(tmp_path / "repo"))


def append(path, text):
    with open(path, "a") as f:
        f.write(text)


def to_crlf(path):
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data.replace(b"\n", b"\r\n"))


def test_the_generated_copies_pass(tree):
    code, output = run_check(tree)
    assert code == 0, output
    assert "PASS: wingman bundled skills valid" in output
    assert "warning" not in output.lower()


def stray_top_level_file(tree):
    append(os.path.join(tree, CURSOR, "notes.md"), "stray\n")


def stray_top_level_readme(tree):
    shutil.copy2(os.path.join(tree, COPILOT, "README.md"), os.path.join(tree, CURSOR, "README.md"))


def extra_nested_file(tree):
    append(os.path.join(tree, CURSOR, "hawkscan", "references", "extra.md"), "extra\n")


def changed_copy(tree):
    append(os.path.join(tree, CURSOR, "hawkscan", "SKILL.md"), "\nchanged\n")


def missing_copy(tree):
    shutil.rmtree(os.path.join(tree, CURSOR, "stackhawk-optimize"))


def empty_folder(tree):
    os.makedirs(os.path.join(tree, CURSOR, "hawkscan", "empty"))


def symlinked_file(tree):
    target = os.path.join(tree, CURSOR, "hawkscan", "SKILL.md")
    os.remove(target)
    os.symlink(os.path.join(tree, COPILOT, "hawkscan", "SKILL.md"), target)


def crlf_copies(tree):
    """Both copies made from CRLF sources: equal to each other, but not what git stores."""
    for top in (COPILOT, CURSOR):
        to_crlf(os.path.join(tree, top, "stackhawk-api", "SKILL.md"))


def cursor_rules_in_the_claude_wingman(tree):
    os.makedirs(os.path.join(tree, "plugins/wingman/rules"))
    shutil.copy2(os.path.join(tree, "cursor-src/rules/stackhawk.mdc"),
                 os.path.join(tree, "plugins/wingman/rules/stackhawk.mdc"))


def cursor_rules_in_the_claude_hawkscan(tree):
    os.makedirs(os.path.join(tree, "plugins/hawkscan/rules"))
    shutil.copy2(os.path.join(tree, "cursor-src/rules/stackhawk.mdc"),
                 os.path.join(tree, "plugins/hawkscan/rules/stackhawk.mdc"))


def changed_hawkscan_copy(tree):
    append(os.path.join(tree, CURSOR_HAWKSCAN, "hawkscan", "references", "scan-policy.md"), "\nchanged\n")


def missing_hawkscan_copy(tree):
    shutil.rmtree(os.path.join(tree, CURSOR_HAWKSCAN, "hawkscan"))


def crlf_hawkscan_copy(tree):
    to_crlf(os.path.join(tree, CURSOR_HAWKSCAN, "hawkscan", "SKILL.md"))


@pytest.mark.parametrize("damage, expected", [
    (stray_top_level_file, f"{CURSOR} differs from {COPILOT}"),
    (stray_top_level_readme, f"{CURSOR} differs from {COPILOT}"),
    (extra_nested_file, f"{CURSOR} differs from {COPILOT}"),
    (changed_copy, f"{CURSOR} differs from {COPILOT}"),
    (missing_copy, f"{CURSOR} differs from {COPILOT}"),
    (empty_folder, f"{CURSOR} differs from {COPILOT}"),
    (symlinked_file, f"{CURSOR} differs from {COPILOT}"),
    (crlf_copies, "CR line endings in the bundled skill copies"),
    (cursor_rules_in_the_claude_wingman, "plugins/wingman/rules exists"),
    (cursor_rules_in_the_claude_hawkscan, "plugins/hawkscan/rules exists"),
    (changed_hawkscan_copy, f"{CURSOR_HAWKSCAN} differs from {HAWKSCAN}"),
    (missing_hawkscan_copy, f"{CURSOR_HAWKSCAN} differs from {HAWKSCAN}"),
    (crlf_hawkscan_copy, "CR line endings in the bundled skill copies"),
], ids=lambda value: getattr(value, "__name__", None))
def test_the_check_fails_on_a_damaged_copy(tree, damage, expected):
    damage(tree)
    code, output = run_check(tree)
    assert code != 0, output
    assert expected in output, output
    assert "warning" not in output.lower()
