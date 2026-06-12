#!/usr/bin/env python3
"""Generate the agent-skills-marketplace catalogs from this repo's local catalogs.

The marketplace repo (stackhawk/agent-skills-marketplace) holds curated,
version-pinned catalogs that point BACK at this repo at a tagged release. The
in-repo catalogs (.claude-plugin/marketplace.json, .codex-plugin/marketplace.json)
use LOCAL-path plugin sources (./plugins/<name>) because the plugin dirs are
co-located. A marketplace consumer, however, clones the marketplace repo — the
plugins are NOT there — so each plugin source must be a REMOTE github source that
points at this repo, at a subdirectory `path`, pinned to a tag + sha.

The original hand-maintained marketplace catalogs omitted `path`, so every tool
resolved this repo's ROOT and failed to find the plugins (which live under
plugins/<name>). This generator is the single source of truth that prevents that:
local-path source  ->  {source:github, repo, path:"plugins/<name>", ref, sha}

The release publisher (release.yml `update-marketplace`) runs this against the
release tag and pushes the output into the marketplace repo. It is also exercised
by marketplace-install-verify.yml, which installs the generated catalogs through
each tool to prove they resolve.

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

# Catalogs that use the github-remote-source model (path + ref + sha). Gemini
# (gemini-extension.json, installed direct from the repo URL) and Copilot (reads
# the .claude-plugin catalog) are intentionally not separate outputs here.
CATALOG_SUBDIRS = (".claude-plugin", ".codex-plugin")

# Default curation: the set currently published to the marketplace. Keeping this
# explicit avoids silently promoting in-development plugins to the public catalog.
DEFAULT_PLUGINS = ["hawkscan", "stackhawk-api"]


def subpath_from_local_source(source):
    """Local source -> 'plugins/<name>'. Accepts the claude string form
    ('./plugins/x') and the codex object form ({'source':'local','path':'./plugins/x'})."""
    raw = source.get("path", "") if isinstance(source, dict) else source
    return raw.lstrip("./")


def remote_source(flavor, repo, subpath, tag, sha):
    """Build the pinned remote plugin source. The two catalog flavors use DIFFERENT
    remote-source schemas (verified by marketplace-install-verify.yml):

      claude / copilot (.claude-plugin): {source:"github", repo, path:"plugins/x", ref, sha}
        Claude Code resolves it; GitHub Copilot CLI reads the same .claude-plugin
        catalog and resolves it too — no Copilot-specific manifest needed.

      codex (.codex-plugin): {source:"git-subdir", url, path:"./plugins/x", ref, sha}
        Codex does NOT understand the "github" source and silently finds no plugin;
        it requires the "git-subdir" type with a full git URL and a `./`-relative path.
    """
    if flavor == "codex":
        return {
            "source": "git-subdir",
            "url": f"https://github.com/{repo}.git",
            "path": f"./{subpath}",
            "ref": tag,
            "sha": sha,
        }
    return {"source": "github", "repo": repo, "path": subpath, "ref": tag, "sha": sha}


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

    for subdir in CATALOG_SUBDIRS:
        flavor = "codex" if subdir == ".codex-plugin" else "claude"
        catalog = load_local_catalog(subdir)
        out, names = transform(flavor, catalog, args.repo, args.tag, args.sha, allow, descriptions)
        if allow is not None:
            missing = [n for n in allow if n not in names]
            if missing:
                print(f"ERROR: {subdir}: requested plugins not in local catalog: {missing}",
                      file=sys.stderr)
                sys.exit(1)
        out_subdir = os.path.join(args.out_dir, subdir)
        os.makedirs(out_subdir, exist_ok=True)
        out_path = os.path.join(out_subdir, "marketplace.json")
        with open(out_path, "w") as f:
            f.write(json.dumps(out, indent=2) + "\n")
        print(f"wrote {subdir}/marketplace.json @ {args.tag} ({args.sha[:7]}): {names}")


if __name__ == "__main__":
    main()
