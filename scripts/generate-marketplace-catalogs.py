#!/usr/bin/env python3
"""Generate remote-source catalogs for local install verification.

The published agent-skills-marketplace now vendors the released plugin folders
and uses local Claude sources. Its own scripts/sync-agent-skills.py creates the
release layout. This helper remains for marketplace-install-verify.yml, which
tests pinned remote-source installs from a disposable local catalog. It does not
write the published marketplace.

Three flavors, three remote-source schemas, verified empirically (no-SSH-keys
Docker containers, current CLIs) because each tool's plugin-install code path
handles "github" and "git-subdir" sources differently:

  claude (.claude-plugin):   {source:"git-subdir", url, path:"plugins/x", ref, sha}
  codex  (.codex-plugin,
          .agents/plugins):  {source:"git-subdir", url, path:"./plugins/x", ref, sha}
  copilot (.github/plugin):  {source:"github", repo, path:"plugins/x", ref, sha}

Claude Code's plugin install/update path unconditionally builds an SSH clone URL
(git@github.com:...) for "github"-type sources, with no HTTPS fallback — it hard
fails with "Host key verification failed" on any machine without SSH keys for
github.com. ("marketplace add" has a separate SSH-probe-then-HTTPS-fallback path
for fetching the catalog itself, which is why `marketplace add` can succeed while
the following `plugin install` fails.) "git-subdir" takes an explicit HTTPS url and
honors it verbatim, sidestepping the SSH path entirely. Since the repo is public,
HTTPS needs no auth, so this works regardless of the installing machine's SSH setup.

Codex's CLI does NOT understand "github" sources at all (silently finds no plugin)
and additionally requires the `./`-relative path prefix — unrelated to the SSH bug,
just a different incompatibility.

GitHub Copilot CLI's "github" source install already works fine over HTTPS (no SSH
bug there) — but Copilot's schema rejects "git-subdir" outright ("Invalid input").
So Copilot needs to keep the working github+path schema, in its own catalog file
Claude Code never looks at: Copilot's marketplace discovery tries, in order,
marketplace.json, .plugin/marketplace.json, .github/plugin/marketplace.json,
.claude-plugin/marketplace.json — so publishing Copilot's catalog at
.github/plugin/marketplace.json means Copilot finds it before ever reaching
.claude-plugin/marketplace.json (which is now git-subdir, incompatible with it),
while Claude Code (which only ever reads .claude-plugin/marketplace.json) is
unaffected by the new file's existence.

The original hand-maintained remote catalogs omitted `path` entirely, so every
tool resolved this repo's root instead of plugins/<name>. This test fixture keeps
the remote-source compatibility checks for Codex and Copilot, and exercises the
Claude git-subdir install path separately from the published local-path catalog.

Usage:
  generate-marketplace-catalogs.py --tag v1.13.0 --sha <40-char-sha> --out-dir DIR
      [--repo stackhawk/agent-skills] [--plugins hawkscan,stackhawk-api]

  --plugins  Comma-separated allowlist controlling which plugins the marketplace
             publishes (curation). Default mirrors the currently-published set.
             Pass "all" to publish every plugin in the local catalog.
"""
import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Gemini (gemini-extension.json, installed direct from the repo URL) is
# intentionally not a separate output here — it doesn't go through this
# marketplace-catalog model at all.
# Per-flavor IO. `read` is the local in-repo catalog we pull plugin metadata from;
# `writes` are catalog paths in the local verification fixture. Codex's CURRENT CLI
# reads .agents/plugins/marketplace.json (verified against the real #1 codex
# marketplace); the legacy .codex-plugin/marketplace.json is also emitted for older
# CLIs. Copilot reads its own catalog (see module docstring) built from the same
# richer claude-flavor local catalog, so its `read` also points at .claude-plugin.
FLAVORS = (
    {"flavor": "claude", "read": ".claude-plugin", "writes": [".claude-plugin/marketplace.json"]},
    {"flavor": "codex", "read": ".codex-plugin",
     "writes": [".agents/plugins/marketplace.json", ".codex-plugin/marketplace.json"]},
    {"flavor": "copilot", "read": ".claude-plugin", "writes": [".github/plugin/marketplace.json"]},
)

# Default curation: the set currently published to the marketplace. Keeping this
# explicit avoids silently promoting in-development plugins to the public catalog.
# NOTE: every plugin documented as marketplace-installable in README.md must be
# listed here for the local install verification workflow. The marketplace repo
# has its own curated plugin mapping in sources.json for published releases.
DEFAULT_PLUGINS = [
    "hawkscan",
    "stackhawk-api",
    "hawkscan-ci",
    "stackhawk-data-seed",
    "stackhawk-optimize",
    "wingman",
]


def subpath_from_local_source(source):
    """Local source -> 'plugins/<name>'. Accepts the claude string form
    ('./plugins/x') and the codex object form ({'source':'local','path':'./plugins/x'})."""
    raw = source.get("path", "") if isinstance(source, dict) else source
    return raw.lstrip("./")


def remote_source(flavor, repo, subpath, tag, sha):
    """Build the pinned remote plugin source. Schema differs per flavor — see the
    module docstring for why each tool needs a different one."""
    if flavor == "copilot":
        return {"source": "github", "repo": repo, "path": subpath, "ref": tag, "sha": sha}
    path = f"./{subpath}" if flavor == "codex" else subpath
    return {
        "source": "git-subdir",
        "url": f"https://github.com/{repo}.git",
        "path": path,
        "ref": tag,
        "sha": sha,
    }


def load_local_catalog(subdir):
    with open(os.path.join(REPO_ROOT, subdir, "marketplace.json")) as f:
        return json.load(f)


def transform(flavor, catalog, repo, tag, sha, allow, descriptions):
    """Rewrite each plugin's source to a pinned remote source (schema per flavor),
    filter to the curation allowlist, and backfill description/homepage from the
    richest catalog."""
    version = tag.lstrip("v")
    out = dict(catalog)
    plugins = []
    for p in catalog.get("plugins", []):
        if allow is not None and p["name"] not in allow:
            continue
        np = dict(p)
        subpath = subpath_from_local_source(p["source"])
        np["source"] = remote_source(flavor, repo, subpath, tag, sha)
        np["version"] = version
        # Backfill cosmetic fields (the codex catalog is sparser than claude's).
        meta = descriptions.get(p["name"], {})
        if not np.get("description") and meta.get("description"):
            np["description"] = meta["description"]
        if not np.get("homepage") and meta.get("homepage"):
            np["homepage"] = meta["homepage"]
        plugins.append(np)
    out["plugins"] = plugins
    return out, [pl["name"] for pl in plugins]


def main():
    ap = argparse.ArgumentParser(description="Generate marketplace catalogs.")
    ap.add_argument("--tag", required=True, help="Release tag, e.g. v1.13.0")
    ap.add_argument("--sha", required=True, help="Commit sha the tag points at")
    ap.add_argument("--out-dir", required=True, help="Output dir (marketplace repo root)")
    ap.add_argument("--repo", default="stackhawk/agent-skills")
    ap.add_argument("--plugins", default=",".join(DEFAULT_PLUGINS),
                    help='Curation allowlist (comma-separated), or "all".')
    args = ap.parse_args()

    if args.plugins.strip().lower() == "all":
        allow = None
    else:
        allow = [x.strip() for x in args.plugins.split(",") if x.strip()]

    # Richest metadata source for backfill: the claude catalog (has description+homepage).
    claude = load_local_catalog(".claude-plugin")
    descriptions = {
        p["name"]: {"description": p.get("description"), "homepage": p.get("homepage")}
        for p in claude.get("plugins", [])
    }

    for spec in FLAVORS:
        flavor = spec["flavor"]
        catalog = load_local_catalog(spec["read"])
        out, names = transform(flavor, catalog, args.repo, args.tag, args.sha, allow, descriptions)
        if allow is not None:
            missing = [n for n in allow if n not in names]
            if missing:
                print(f"ERROR: {spec['read']}: requested plugins not in local catalog: {missing}",
                      file=sys.stderr)
                sys.exit(1)
        out_json = json.dumps(out, indent=2) + "\n"
        for rel in spec["writes"]:
            out_path = os.path.join(args.out_dir, rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                f.write(out_json)
            print(f"wrote {rel} @ {args.tag} ({args.sha[:7]}): {names}")


if __name__ == "__main__":
    main()
