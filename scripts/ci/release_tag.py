#!/usr/bin/env python3
"""Resolve and recheck the immutable commit selected by a release-tag push."""

import os
import re
import subprocess
import sys


TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


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
        raise ValueError(f"{tag} no longer points to the triggering commit {sha}")


def resolve():
    if (os.environ.get("GITHUB_EVENT_NAME") != "push"
            or os.environ.get("GITHUB_REF_TYPE") != "tag"
            or os.environ.get("GITHUB_EVENT_CREATED") != "true"
            or os.environ.get("GITHUB_EVENT_DELETED") != "false"):
        raise ValueError("release requires a newly created tag push")
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        raise ValueError("release requires a tag ref")
    tag = ref.removeprefix("refs/tags/")
    version = validate_tag(tag)
    sha = os.environ.get("GITHUB_SHA", "")
    if not SHA.fullmatch(sha) or git("rev-parse", "HEAD") != sha:
        raise ValueError("checkout HEAD differs from the triggering commit")
    verify(tag, sha)
    git("merge-base", "--is-ancestor", sha, "origin/main")
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
