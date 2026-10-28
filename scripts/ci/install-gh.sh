#!/usr/bin/env bash
set -euo pipefail

# ─── Install the GitHub CLI on a runner that does not ship it ───
# The agent-skills runner image has no `gh`. Pinned version, SHA-256 checked against the digests
# of the release's checksums file; the binary lands in $RUNNER_TEMP/gh/bin and on the job's PATH.
# Bump GH_VERSION and both digests together (https://github.com/cli/cli/releases, gh_<v>_checksums.txt).

GH_VERSION="2.103.3"
SHA256_amd64="4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d"
SHA256_arm64="ee32df2323c8847f5fac6cb6b4b69ca75828e9329a8f22f677021f7b3306ce63"

case "$(uname -m)" in
  x86_64 | amd64)  arch=amd64; expected="$SHA256_amd64" ;;
  aarch64 | arm64) arch=arm64; expected="$SHA256_arm64" ;;
  *) echo "ERROR: no pinned gh build for $(uname -m)" >&2; exit 1 ;;
esac

dest="${RUNNER_TEMP:-$(mktemp -d)}/gh"
mkdir -p "$dest/bin"
tarball="gh_${GH_VERSION}_linux_${arch}.tar.gz"

curl -fsSL --retry 3 -o "$dest/$tarball" "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${tarball}"
echo "${expected}  ${dest}/${tarball}" | sha256sum --check --status || {
  echo "ERROR: ${tarball} does not match the pinned SHA-256" >&2
  exit 1
}
tar -xzf "$dest/$tarball" -C "$dest" --strip-components=2 "gh_${GH_VERSION}_linux_${arch}/bin/gh"
mv "$dest/gh" "$dest/bin/gh"
rm -f "$dest/$tarball"

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$dest/bin" >> "$GITHUB_PATH"
fi
"$dest/bin/gh" --version
