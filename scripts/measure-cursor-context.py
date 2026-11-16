#!/usr/bin/env python3
"""Measure the context that a StackHawk Cursor install puts in front of the model.

Cursor puts the body of every `alwaysApply: true` rule into every chat, lists the
description of every agent-requested rule (description, no globs) and of every skill,
and attaches the body of a glob rule when a matching file is in context. This script
derives those loads from the files, so a change that makes the integration heavier
fails a check instead of reaching users. It does not run Cursor.

Usage:
  measure-cursor-context.py [--json] [--check] DIR

DIR is a project's `.cursor` directory, a user's `~/.cursor`, or a Cursor plugin
directory. A plugin directory with `.cursor-plugin/plugin.json` uses the `rules` and
`skills` paths of that manifest. `--check` exits 1 when a budget is exceeded.

Byte counts are UTF-8 bytes of what Cursor would load: rule bodies without frontmatter,
descriptions as folded text. About 4 bytes make one token.
"""
import argparse
import json
import os
import re
import sys

# Files a user has in context in common scenarios, relative to the project root.
SCENARIOS = {
    "stackhawk.yml": "stackhawk.yml",
    "ci-workflow": ".github/workflows/ci.yml",
    "dockerfile": "Dockerfile",
    "data-seed": "data-seed/manifest.yaml",
    "source-file": "src/app.py",
}

# Budgets from the Cursor redesign (default load = always-applied bodies + description indexes).
BUDGETS = {
    "always_applied_bytes": 2000,
    "default_load_bytes": 7000,
    "attach:stackhawk.yml": 1500,
    "attach:ci-workflow": 0,
    "attach:dockerfile": 0,
    "attach:data-seed": 0,
    "attach:source-file": 0,
    "dangling_rule_links": 0,
    "duplicated_body_bytes": 0,
}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
KEY_RE = re.compile(r"^([A-Za-z][\w-]*):[ \t]*(.*)$")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
REFERENCE_PATH_RE = re.compile(r"(?<![\w/.-])((?:\.\./|\./)?references/[A-Za-z0-9_.-]+\.md)")


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Return (fields, body) for the small YAML subset that rules and skills use.

    Supports `key: value`, folded (`>`) and literal (`|`) blocks, and `- item` lists.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fields = {}
    lines = match.group(1).split("\n")
    i = 0
    while i < len(lines):
        key_match = KEY_RE.match(lines[i])
        i += 1
        if not key_match:
            continue
        key, value = key_match.group(1), key_match.group(2).strip()
        block = []
        while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
            block.append(lines[i])
            i += 1
        if value in (">", ">-", "|", "|-"):
            parts = [line.strip() for line in block if line.strip()]
            fields[key] = (" " if value.startswith(">") else "\n").join(parts)
        elif value == "":
            items = [unquote(line.strip()[1:]) for line in block if line.strip().startswith("-")]
            fields[key] = items if items else None
        elif value in ("true", "false"):
            fields[key] = value == "true"
        else:
            fields[key] = unquote(value)
    return fields, text[match.end():]


def as_globs(value):
    if not value:
        return []
    if isinstance(value, str):
        return [g.strip() for g in value.split(",") if g.strip()]
    return [g for g in value if g]


def glob_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(f"^{out}$")


def rule_mode(fields):
    """Cursor's order: alwaysApply wins, then globs, then description, else manual."""
    if fields.get("alwaysApply") is True:
        return "always"
    if as_globs(fields.get("globs")):
        return "glob"
    if isinstance(fields.get("description"), str) and fields["description"].strip():
        return "agent-requested"
    return "manual"


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_rules(rules_dir):
    rules = []
    for dirpath, dirnames, filenames in os.walk(rules_dir):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith((".mdc", ".md", ".markdown")):
                continue
            path = os.path.join(dirpath, name)
            fields, body = parse_frontmatter(read_text(path))
            rules.append({
                "path": path,
                "mode": rule_mode(fields),
                "globs": as_globs(fields.get("globs")),
                "description": fields.get("description") or "",
                "body": body,
            })
    return rules


def load_skills(skills_dir):
    skills = []
    if not os.path.isdir(skills_dir):
        return skills
    for name in sorted(os.listdir(skills_dir)):
        skill_md = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(skill_md):
            fields, _ = parse_frontmatter(read_text(skill_md))
            skills.append({"dir": os.path.dirname(skill_md), "description": fields.get("description") or ""})
    return skills


def component_dirs(root):
    """The rules and skills directories Cursor reads for this directory."""
    rules, skills = "rules", "skills"
    manifest = os.path.join(root, ".cursor-plugin", "plugin.json")
    if os.path.isfile(manifest):
        with open(manifest) as f:
            data = json.load(f)
        rules = data.get("rules", rules) if isinstance(data.get("rules", rules), str) else rules
        skills = data.get("skills", skills) if isinstance(data.get("skills", skills), str) else skills
    return os.path.join(root, rules), os.path.join(root, skills)


def dangling_links(rule):
    """Distinct relative paths in a rule (link targets and bare references/ paths) that do not resolve."""
    base = os.path.dirname(rule["path"])
    targets = {t for t in LINK_RE.findall(rule["body"]) if not re.match(r"^(?:[a-z]+:|#|/)", t)}
    targets |= set(REFERENCE_PATH_RE.findall(rule["body"]))
    return sum(1 for t in targets if not os.path.exists(os.path.join(base, t.split("#")[0])))


def skill_bodies(skills):
    bodies = set()
    for skill in skills:
        for dirpath, _dirs, filenames in os.walk(skill["dir"]):
            for name in filenames:
                if name.endswith(".md"):
                    _, body = parse_frontmatter(read_text(os.path.join(dirpath, name)))
                    bodies.add(body.strip())
    return bodies


def measure(root):
    rules_dir, skills_dir = component_dirs(root)
    rules = load_rules(rules_dir)
    skills = load_skills(skills_dir)
    size = lambda s: len(s.encode("utf-8"))
    always = sum(size(r["body"]) for r in rules if r["mode"] == "always")
    requested = sum(size(r["description"]) for r in rules if r["mode"] == "agent-requested")
    skill_index = sum(size(s["description"]) for s in skills)
    attach = {}
    for label, rel in SCENARIOS.items():
        attach[label] = sum(
            size(r["body"]) for r in rules
            if r["mode"] == "glob" and any(glob_regex(g).match(rel) for g in r["globs"])
        )
    bodies = skill_bodies(skills)
    duplicated = sum(size(r["body"]) for r in rules if r["body"].strip() and r["body"].strip() in bodies)
    files = [os.path.join(d, f) for d, _dirs, fs in os.walk(root) for f in fs]
    return {
        "root": root,
        "rules": {mode: sum(1 for r in rules if r["mode"] == mode) for mode in ("always", "glob", "agent-requested", "manual")},
        "skills": len(skills),
        "always_applied_bytes": always,
        "agent_requested_description_bytes": requested,
        "skill_description_bytes": skill_index,
        "default_load_bytes": always + requested + skill_index,
        "attach_bytes": attach,
        "dangling_rule_links": sum(dangling_links(r) for r in rules),
        "duplicated_body_bytes": duplicated,
        "installed_files": len(files),
        "installed_bytes": sum(os.path.getsize(f) for f in files if os.path.isfile(f)),
    }


def budget_failures(report):
    failures = []
    for key, limit in BUDGETS.items():
        value = report["attach_bytes"][key.split(":", 1)[1]] if key.startswith("attach:") else report[key]
        if value > limit:
            failures.append(f"{key} is {value}, budget {limit}")
    return failures


def print_table(report):
    rows = [
        ("rules (always / glob / agent-requested / manual)", " / ".join(str(v) for v in report["rules"].values())),
        ("skills", report["skills"]),
        ("always-applied bytes", report["always_applied_bytes"]),
        ("agent-requested description bytes", report["agent_requested_description_bytes"]),
        ("skill description bytes", report["skill_description_bytes"]),
        ("default load bytes (~tokens)", f"{report['default_load_bytes']} (~{report['default_load_bytes'] // 4})"),
    ]
    rows += [(f"bytes attached on {SCENARIOS[k]}", v) for k, v in report["attach_bytes"].items()]
    rows += [
        ("dangling links in rules", report["dangling_rule_links"]),
        ("rule bodies duplicated in skills (bytes)", report["duplicated_body_bytes"]),
        ("files / bytes under the directory", f"{report['installed_files']} / {report['installed_bytes']}"),
    ]
    width = max(len(label) for label, _ in rows)
    print(f"Cursor context for {report['root']}")
    for label, value in rows:
        print(f"  {label.ljust(width)}  {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dir", help="a .cursor directory or a Cursor plugin directory")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--check", action="store_true", help="exit 1 when a budget is exceeded")
    args = parser.parse_args()
    if not os.path.isdir(args.dir):
        print(f"ERROR: not a directory: {args.dir}", file=sys.stderr)
        return 2
    report = measure(os.path.abspath(args.dir))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)
    if args.check:
        failures = budget_failures(report)
        for failure in failures:
            print(f"BUDGET: {failure}", file=sys.stderr)
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
