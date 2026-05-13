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
        $source = Join-Path $RepoRoot "cursor\.cursor\rules"
        $dest   = Join-Path $HOME   ".cursor\rules"

        if (-not (Test-Path $source)) {
            Write-Error "Cursor rules not found at '$source'. Run 'bash scripts/generate-cursor-rules.sh' first."
            exit 1
        }

        $existing = Get-Item (Join-Path $dest "stackhawk-*.mdc") -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "WARNING: StackHawk Cursor rules already exist in ${dest}\"
            Write-Host "Files that will be overwritten:"
            $existing | ForEach-Object { Write-Host "  $($_.Name)" }
            Write-Host ""
            $confirm = Read-Host "Overwrite? [y/N]"
            if ($confirm -notin @("y", "Y")) {
                Write-Host "Aborted."
                exit 0
            }
        }

        New-Item -ItemType Directory -Force $dest | Out-Null
        Copy-Item (Join-Path $source "stackhawk-*.mdc") $dest -Force
        $count = (Get-Item (Join-Path $dest "stackhawk-*.mdc")).Count
        Write-Host "Installed $count Cursor rules to ${dest}\"
    }

    "copilot" {
        $hawkscanSrc = Join-Path $RepoRoot "plugins\hawkscan\skills\hawkscan"
        $apiSrc      = Join-Path $RepoRoot "plugins\api\skills\api"
        $dest        = Join-Path $HOME ".agents\skills"
        $hawkscanDst = Join-Path $dest "hawkscan"
        $apiDst      = Join-Path $dest "stackhawk-api"

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
