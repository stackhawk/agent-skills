# HawkScan Installation Reference

**Minimum hawk version:** This skill calls `hawk config show <section>` for live config documentation. You need hawk **v6.0.0** or later. Verify with:

```bash
hawk version
hawk config --help
```

If `hawk config` is unrecognized, upgrade hawk before running this skill.

## Contents
- [CLI Installation](#cli-installation)
  - [Windows workstation](#windows-workstation)
  - [Mac workstation](#mac-workstation)
  - [Linux workstation](#linux-workstation)
  - [CI/CD](#cicd)
  - [Kubernetes and other Kube-native platforms](#kubernetes-and-other-kube-native-platforms)
  - [Prerequisites](#prerequisites)
  - [Verify Installation](#verify-installation)
- [Post-Install Setup](#post-install-setup)
  - [Authenticate with hawk init](#authenticate-with-hawk-init)
  - [Non-Interactive Sessions: Set HAWK_API_KEY](#non-interactive-sessions-set-hawk_api_key)
- [Docker (Alternative to CLI)](#docker-alternative-to-cli)

---

## CLI Installation

HawkScan 6 ships as a **single self-contained native binary** per platform — the
runtime is embedded, so **no separate Java install is needed**.

The install scripts are the simplest way to install on a machine without a package
manager or installer. Run them as shown, with their defaults: they install `hawk`
to `~/.local/bin` (`%USERPROFILE%\.local\bin` on Windows) and add that folder to
your PATH. Do not override the install folder or version with environment variables, and do
not build download URLs by hand.

The PATH change reaches new shells only. To run `hawk` in the same session right after
the install script, add the folder to PATH there too, or open a new shell:

```bash
export PATH="$HOME/.local/bin:$PATH"                     # macOS / Linux
```

```powershell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"    # Windows PowerShell
```

Pick the first method that fits the machine, in the order listed for it.

### Windows workstation

1. **MSI installer** (requires admin). Download it from https://docs.stackhawk.com/downloads/
   and run it.
2. **Install script** (PowerShell):

   ```powershell
   irm https://download.stackhawk.com/hawk/install.ps1 | iex
   ```

   From `cmd.exe`, run `powershell -Command "irm https://download.stackhawk.com/hawk/install.ps1 | iex"`.
3. **Docker** — see [Docker](#docker-alternative-to-cli).

### Mac workstation

1. **Homebrew:**

   ```bash
   brew tap stackhawk/cli
   brew trust stackhawk/cli
   brew install hawk
   ```

2. **`.pkg` installer.** Download it from https://docs.stackhawk.com/downloads/ and run it.
3. **Install script:**

   ```bash
   curl -fsSL https://download.stackhawk.com/hawk/install.sh | sh
   ```

4. **Docker** — see [Docker](#docker-alternative-to-cli).

### Linux workstation

1. **Install script:**

   ```bash
   curl -fsSL https://download.stackhawk.com/hawk/install.sh | sh
   ```

2. **Docker** — see [Docker](#docker-alternative-to-cli).

### CI/CD

1. **GitHub Actions:** the HawkScan Action (`stackhawk/hawkscan-action`).
2. **Azure Pipelines:** the StackHawk Azure Extension.
3. **Install script.** In CI the script leaves PATH alone, so add the install folder
   to PATH on the next line, then call plain `hawk`:

   ```bash
   curl -fsSL https://download.stackhawk.com/hawk/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   hawk version
   ```

   Where later steps do not share a shell, use the CI system's own mechanism instead
   of `export` (for example `echo "$HOME/.local/bin" >> "$GITHUB_PATH"` on GitHub Actions).
4. **Docker** — see [Docker](#docker-alternative-to-cli).

The `hawkscan-ci` skill writes the pipeline for a given provider.

### Kubernetes and other Kube-native platforms

Use the Docker image: `stackhawk/hawkscan:latest`.

### Prerequisites

- **None for the runtime** — the binary bundles everything (no Java install required).
- The install script for macOS and Linux uses `curl`, which is standard on developer
  machines and CI runners.

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

### Non-Interactive Sessions: Set `HAWK_API_KEY`

In any non-interactive session — a CI pipeline, a container, a headless agent — `hawk init`
has no browser and no person to answer it. Set `HAWK_API_KEY` (as a secret in CI) and prefix
each invocation:

```bash
API_KEY=$HAWK_API_KEY hawk scan
```

The CLI resolves keys in this order: `--api-key` flag → `API_KEY` env var → `~/.hawk/hawk.properties`.

For interactive local use, `hawk init --browser` is the preferred approach — no env var needed.

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
