#!/usr/bin/env python3
"""Resolve and recheck the release tag that a Publish release run was started with.

resolve turns the tag input into the commit to publish: the tag must be a stable vX.Y.Z tag that
exists on origin and names a commit on main. verify checks later that the tag still names that
commit, so a tag that was moved after resolve cannot change what a write job publishes.
"""

import os
import re
import subprocess
import sys


TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
# What the later jobs run from the tag's own tree. A tag made before these existed cannot be published.
RELEASE_SCRIPTS = ("scripts/ci/release_tag.py", "scripts/ci/marketplace_release_order.py")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def remote_commit(tag):
    ref = f"refs/tags/{tag}"
    lines = git("ls-remote", "--tags", "origin", ref, ref + "^{}")
    refs = {}
    for line in lines.splitlines():
        sha, name = line.split("\t", 1)
        refs[name] = sha
    commit = refs.get(ref + "^{}", refs.get(ref))
    if not commit or not SHA.fullmatch(commit):
        raise ValueError(f"release tag {tag} is missing from origin")
    return commit


def validate_tag(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"{tag!r} is not a supported vX.Y.Z release tag")
    return ".".join(match.groups())


def verify(tag, sha):
    validate_tag(tag)
    if not SHA.fullmatch(sha):
        raise ValueError("the release commit is not a full commit SHA")
    local = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    remote = remote_commit(tag)
    if local != sha or remote != sha:
        raise ValueError(f"{tag} no longer points to the release commit {sha}")


def resolve():
    if (os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("publishing requires a workflow_dispatch run on main")
    tag = os.environ.get("RELEASE_TAG", "")
    version = validate_tag(tag)
    sha = remote_commit(tag)
    verify(tag, sha)
    git("merge-base", "--is-ancestor", sha, "origin/main")
    for path in RELEASE_SCRIPTS:
        try:
            git("cat-file", "-e", f"{sha}:{path}")
        except subprocess.CalledProcessError:
            raise ValueError(f"{tag} has no {path}: it was tagged before Publish release existed")
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise ValueError("GITHUB_OUTPUT is required")
    with open(output, "a", encoding="utf-8") as f:
        f.write(f"tag={tag}\nversion={version}\nsha={sha}\n")
    print(f"Release {tag} from {sha}")


def main():
    if sys.argv[1:] == ["resolve"]:
        resolve()
    elif sys.argv[1:] == ["verify"]:
        verify(os.environ["RELEASE_TAG"], os.environ["RELEASE_SHA"])
    else:
        raise ValueError("usage: release_tag.py resolve|verify")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
