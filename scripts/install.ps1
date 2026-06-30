#Requires -Version 5.1
param(
    [Parameter(Mandatory)]
    [ValidateSet("cursor", "copilot")]
    [string]$Platform
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

switch ($Platform) {
    "cursor" {
        $rulesSource      = Join-Path $RepoRoot "cursor\.cursor\rules"
        $rulesDest        = Join-Path $HOME ".cursor\rules"
        $skillsDest       = Join-Path $HOME ".cursor\skills"
        $hooksDest        = Join-Path $HOME ".cursor\hooks"
        $pluginsSource    = Join-Path $RepoRoot "plugins"
        $cursorHooksSrc   = Join-Path $RepoRoot "plugins\hawkscan\hooks\cursor"

        if (-not (Test-Path $rulesSource)) {
            Write-Error "Cursor rules not found at '$rulesSource'. Run 'bash scripts/generate-cursor-rules.sh' first."
            exit 1
        }
        if (@(Get-ChildItem -Path (Join-Path $rulesSource "stackhawk-*.mdc") -ErrorAction SilentlyContinue).Count -eq 0) {
            Write-Error "No stackhawk-*.mdc files found. Run 'bash scripts/generate-cursor-rules.sh' first."
            exit 1
        }

        $existingMarkers = @()
        if (Test-Path (Join-Path $rulesDest "stackhawk-hawkscan.mdc")) { $existingMarkers += "rules" }
        if (Test-Path (Join-Path $skillsDest "hawkscan"))               { $existingMarkers += "skills" }
        if (Test-Path (Join-Path $HOME ".cursor\hooks.json"))           { $existingMarkers += "hooks" }

        if ($existingMarkers.Count -gt 0) {
            Write-Host "WARNING: StackHawk Cursor artifacts already exist: $($existingMarkers -join ', ')"
            Write-Host ""
            $confirm = Read-Host "Overwrite? [y/N]"
            if ($confirm -notin @("y", "Y")) {
                Write-Host "Aborted."
                exit 0
            }
        }

        # Rules
        New-Item -ItemType Directory -Force $rulesDest | Out-Null
        Copy-Item (Join-Path $rulesSource "stackhawk-*.mdc") $rulesDest -Force
        $count = @(Get-ChildItem -Path (Join-Path $rulesDest "stackhawk-*.mdc") -ErrorAction SilentlyContinue).Count
        Write-Host "Installed $count Cursor rules to ${rulesDest}\"

        # Skills
        foreach ($skill in @(
            @{ src = "hawkscan\skills\hawkscan";                        dst = "hawkscan" },
            @{ src = "api\skills\api";                                  dst = "api" },
            @{ src = "hawkscan-ci\skills\hawkscan-ci";                  dst = "hawkscan-ci" },
            @{ src = "stackhawk-data-seed\skills\stackhawk-data-seed";  dst = "stackhawk-data-seed" },
            @{ src = "optimize\skills\optimize";                        dst = "optimize" }
        )) {
            $d = Join-Path $skillsDest $skill.dst
            New-Item -ItemType Directory -Force $d | Out-Null
            Copy-Item -Recurse (Join-Path $pluginsSource "$($skill.src)\*") $d -Force
        }
        Write-Host "Installed 5 Cursor skills to ${skillsDest}\"
        Write-Host "  hawkscan\            -- DAST scanning skill"
        Write-Host "  api\                 -- StackHawk API reporting skill"
        Write-Host "  hawkscan-ci\         -- CI/CD pipeline skill"
        Write-Host "  stackhawk-data-seed\ -- Data seed skill"
        Write-Host "  optimize\            -- Scan optimization skill"

        # Hooks
        New-Item -ItemType Directory -Force $hooksDest | Out-Null
        Copy-Item (Join-Path $cursorHooksSrc "hooks.json") (Join-Path $HOME ".cursor\hooks.json") -Force
        Copy-Item (Join-Path $cursorHooksSrc "stop.sh")    (Join-Path $hooksDest "stop.sh") -Force
        Write-Host "Installed Cursor hooks to $HOME\.cursor\"
        Write-Host "  hooks.json           -- hook configuration"
        Write-Host "  hooks\stop.sh        -- scan reminder on session end"
    }

    "copilot" {
        $hawkscanSrc = Join-Path $RepoRoot "plugins\hawkscan\skills\hawkscan"
        $apiSrc      = Join-Path $RepoRoot "plugins\api\skills\api"
        $dest        = Join-Path $HOME ".agents\skills"
        $hawkscanDst = Join-Path $dest "hawkscan"
        $apiDst      = Join-Path $dest "stackhawk-api"

        if (-not (Test-Path $hawkscanSrc)) {
            Write-Error "Copilot skill source not found at '$hawkscanSrc'. Is the repo fully checked out?"
            exit 1
        }
        if (-not (Test-Path $apiSrc)) {
            Write-Error "Copilot skill source not found at '$apiSrc'. Is the repo fully checked out?"
            exit 1
        }

        $existingDirs = @()
        if (Test-Path $hawkscanDst) { $existingDirs += "hawkscan\" }
        if (Test-Path $apiDst)      { $existingDirs += "stackhawk-api\" }

        if ($existingDirs.Count -gt 0) {
            Write-Host "WARNING: StackHawk skills already exist in ${dest}\"
            Write-Host "Directories that will be overwritten:"
            $existingDirs | ForEach-Object { Write-Host "  $_" }
            Write-Host ""
            $confirm = Read-Host "Overwrite? [y/N]"
            if ($confirm -notin @("y", "Y")) {
                Write-Host "Aborted."
                exit 0
            }
        }

        New-Item -ItemType Directory -Force $hawkscanDst | Out-Null
        New-Item -ItemType Directory -Force $apiDst      | Out-Null
        Copy-Item -Recurse "$hawkscanSrc\*" $hawkscanDst -Force
        Copy-Item -Recurse "$apiSrc\*"      $apiDst      -Force
        Write-Host "Installed StackHawk skills to ${dest}\"
        Write-Host "  hawkscan\       -- DAST scanning skill"
        Write-Host "  stackhawk-api\  -- API reporting skill"
    }
}
