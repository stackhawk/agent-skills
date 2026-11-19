#!/usr/bin/env python3
"""Keep a tag retry from replacing a newer published marketplace pin."""

import json
import re
import sys


TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def version(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"invalid release tag {tag!r}")
    return tuple(map(int, match.groups()))


def order(sources, tag, sha):
    incoming = version(tag)
    if not SHA.fullmatch(sha):
        raise ValueError("invalid release commit SHA")
    current_tag, current_sha = sources["tag"], sources["sha"]
    current = version(current_tag)
    if not SHA.fullmatch(current_sha):
        raise ValueError("invalid marketplace source SHA")
    if incoming == current:
        if tag != current_tag or sha != current_sha:
            raise ValueError(f"marketplace already records {current_tag} at a different commit")
        return "current"
    if incoming < current:
        return "older"
    return "newer"


def main():
    if len(sys.argv) != 4:
        raise ValueError("usage: marketplace_release_order.py SOURCES_JSON TAG SHA")
    with open(sys.argv[1], encoding="utf-8") as f:
        sources = json.load(f)
    print(order(sources, sys.argv[2], sys.argv[3]))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
