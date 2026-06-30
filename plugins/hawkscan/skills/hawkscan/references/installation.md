# HawkScan Installation Reference

**Minimum hawk version:** This skill calls `hawk config show <section>` for live config documentation. You need hawk **v6.0.0** or later. Verify with:

```bash
hawk version
hawk config --help
```

If `hawk config` is unrecognized, upgrade hawk before running this skill.

## Contents
- [CLI Installation](#cli-installation)
  - [Homebrew (macOS — recommended)](#homebrew-macos--recommended)
  - [Download the binary (macOS / Linux)](#download-the-binary-macos--linux)
  - [macOS — .pkg installer](#macos--pkg-installer)
  - [Windows — .msi installer (PowerShell)](#windows--msi-installer-powershell)
  - [Pin a specific version](#pin-a-specific-version)
  - [Prerequisites](#prerequisites)
  - [Verify Installation](#verify-installation)
- [Post-Install Setup](#post-install-setup)
  - [Authenticate with hawk init](#authenticate-with-hawk-init)
  - [CI/CD: Set HAWK_API_KEY as a Secret](#cicd-set-hawk_api_key-as-a-secret)
- [Docker (Alternative to CLI)](#docker-alternative-to-cli)

---

## CLI Installation

HawkScan 6 ships as a **single self-contained native binary** per platform — the
runtime is embedded, so **no separate Java install is needed**. The source of truth
for the current version and every download URL is the manifest:

```
https://download.stackhawk.com/hawkdocs/hawk.manifest.json
```

URL pattern: `https://download.stackhawk.com/hawk/<version>/<group>/hawk[.pkg|.exe|.msi]`,
where `<group>` is one of `darwin-arm64`, `darwin-x64`, `linux-x64`, `linux-aarch64`,
`windows-x64`, `windows-arm64`. Always resolve the URL from the manifest rather than
hand-building it — the version and asset list are authoritative there.

### Homebrew (macOS — recommended)

```bash
brew tap stackhawk/cli
brew trust stackhawk/cli
brew install hawk
```

### Download the binary (macOS / Linux)

```bash
MANIFEST=https://download.stackhawk.com/hawkdocs/hawk.manifest.json
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)              GROUP=darwin-arm64 ;;
  Darwin/x86_64)             GROUP=darwin-x64 ;;
  Linux/x86_64)              GROUP=linux-x64 ;;
  Linux/aarch64|Linux/arm64) GROUP=linux-aarch64 ;;
  *) echo "unsupported platform"; exit 1 ;;
esac
url=$(curl -fsSL "$MANIFEST" | jq -r --arg g "$GROUP" \
  '.latest.assets[] | select(.asset.group == $g and (.url | endswith("/hawk"))) | .url')
curl -fsSL "$url" -o hawk && chmod +x hawk && sudo mv hawk /usr/local/bin/hawk
hawk version
```

### macOS — `.pkg` installer

```bash
url=$(curl -fsSL https://download.stackhawk.com/hawkdocs/hawk.manifest.json \
  | jq -r '.latest.assets[] | select(.asset.group == "darwin-arm64" and (.url | endswith(".pkg"))) | .url')   # use darwin-x64 on Intel
curl -fsSL "$url" -o hawk.pkg && sudo installer -pkg hawk.pkg -target /
```

### Windows — `.msi` installer (PowerShell)

```powershell
$m   = Invoke-RestMethod https://download.stackhawk.com/hawkdocs/hawk.manifest.json
$url = ($m.latest.assets | Where-Object { $_.asset.group -eq 'windows-x64' -and $_.url.EndsWith('.msi') }).url
Invoke-WebRequest $url -OutFile hawk.msi
Start-Process msiexec.exe -ArgumentList "/i hawk.msi /passive" -Wait
```

Homebrew and a browser download are also available — see the downloads page:
https://docs.stackhawk.com/downloads/

### Pin a specific version

The snippets above track `.latest`. To pin, replace the version segment:
`https://download.stackhawk.com/hawk/<X.Y.Z>/<group>/hawk`. The manifest's `supported`
array lists available versions, and each asset carries a `sha256` for integrity checks.

### Prerequisites

- **None for the runtime** — the binary bundles everything (no Java install required).
- The install snippets use `curl` and `jq` (to parse the manifest); both are standard
  on developer machines and CI runners.

### Verify Installation

```bash
hawk version
```

---

## Post-Install Setup

### Authenticate with `hawk init`

```bash
hawk init --browser
```

This opens a browser window for device-flow authentication — log in and approve the
request. No API key to copy or paste; the resulting credentials are saved to
`~/.hawk/hawk.properties`.

**No browser available (headless/remote)?** Run `hawk init` without `--browser` and
paste an API key (format: `hawk.xxxxxxxxxx.xxxxxxxxxx`) when prompted:
1. Log into https://app.stackhawk.com
2. Go to Settings → API Keys
3. Create or copy an existing key (keys only display once on creation)

### CI/CD: Set `HAWK_API_KEY` as a Secret

For pipeline runs where `hawk init --browser` cannot be used interactively, set `HAWK_API_KEY` as a
CI secret and prefix each invocation:

```bash
API_KEY=$HAWK_API_KEY hawk scan
```

The CLI resolves keys in this order: `--api-key` flag → `API_KEY` env var → `~/.hawk/hawk.properties`.

For local/agentic use, `hawk init --browser` is the preferred approach — no env var needed.

---

## Docker (Alternative to CLI)

If you prefer Docker over the CLI:

```bash
docker pull stackhawk/hawkscan:latest
```

No Java or CLI installation needed. See `references/docker-usage.md` for run commands.

**Trade-offs:**
- Docker requires `--network host` (Linux) or `host.docker.internal` (Mac/Windows) to
  reach apps on localhost
- CLI is faster for local iteration and has simpler localhost networking
- Docker is better for CI environments that already have Docker available
