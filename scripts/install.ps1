#Requires -Version 5.1
# Copies StackHawk agent skills for platforms that require manual installation
# (Cursor, Copilot). Same layout as scripts/install.sh.
#
# Usage, from a clone of stackhawk/agent-skills-marketplace (the released build):
#   .\install\install.ps1 -Platform cursor -Target .        # project install
#   .\install\install.ps1 -Platform cursor                  # user level: skills and stop hook
#   .\install\install.ps1 -Platform copilot -Target .
#
# From a clone of stackhawk/agent-skills, scripts\install.ps1 installs the unreleased
# development build the same way. The two name some plugin folders differently (plugins/api
# in a clone, plugins/stackhawk-api in a snapshot), so each skill is found by its catalog
# plugin name first, then by its source folder. Both install the canonical skills of plugins/,
# never the bundled wingman copies (plugins/wingman/copilot-skills/, cursor-plugins/wingman/
# or bundles/wingman/). The rules and the stop hook come from cursor-plugins/hawkscan/, the
# Cursor-only hawkscan plugin: the same folder in both clones (in agent-skills, a generated
# copy of cursor-src/).
param(
    [Parameter(Mandatory)]
    [ValidateSet("cursor", "copilot")]
    [string]$Platform,

    # Project directory. The default is your home directory, which for Cursor is a
    # user-level install: the skills and the stop hook, no rules.
    [string]$Target = $HOME
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Fail([string]$Message) {
    [Console]::Error.WriteLine("ERROR: $Message")
    exit 1
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

# The full path with every symbolic link and junction resolved, in each part of the path,
# so that a home directory reached through a linked folder is still home (like pwd -P).
function Get-PhysicalPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root
    $parts = $full.Substring($root.Length).Split([char[]]@('\', '/'), [System.StringSplitOptions]::RemoveEmptyEntries)
    foreach ($part in $parts) {
        $current = Join-Path $current $part
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($item -and $item.LinkType -and $item.Target) {
            $linkTarget = @($item.Target)[0]
            if (-not [System.IO.Path]::IsPathRooted($linkTarget)) {
                # GetDirectoryName, not Split-Path -Parent: that gives "" for a link directly
                # under the root, such as /var or /tmp on macOS (both link to private/...).
                $linkTarget = Join-Path ([System.IO.Path]::GetDirectoryName($current)) $linkTarget
            }
            $current = Get-PhysicalPath $linkTarget
        }
    }
    $trimmed = $current.TrimEnd('\', '/')
    if ($trimmed) { return $trimmed }
    return $current
}

if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    Fail "Target directory does not exist: $Target"
}
$TargetPath = (Resolve-Path -LiteralPath $Target).ProviderPath

# --- Cursor ---
# Project install: the five skills in .cursor/skills/, the router and stackhawk.yml
# pointer rules in .cursor/rules/, .cursor/hooks/stackhawk-stop.sh, and one stop entry
# merged into .cursor/hooks.json. User-level install (-Target is your home directory):
# the skills and the stop hook only, with the command ./hooks/stackhawk-stop.sh because
# Cursor runs user hooks from ~/.cursor/. The installer replaces only files it owns and
# removes what older versions installed (cursor-legacy-rules.txt beside this script and a
# .cursor/hooks/stop.sh that it wrote). The stop hook is a bash script: on Windows,
# Cursor needs bash (for example Git for Windows) to run it.

# Catalog is the plugin name in the catalog (a snapshot folder); Folder is the source folder.
$CursorSkills = @(
    @{ Name = "hawkscan";            Catalog = "hawkscan";            Folder = "hawkscan";            Label = "DAST scanning skill" },
    @{ Name = "api";                 Catalog = "stackhawk-api";       Folder = "api";                 Label = "StackHawk API reporting skill" },
    @{ Name = "hawkscan-ci";         Catalog = "hawkscan-ci";         Folder = "hawkscan-ci";         Label = "CI/CD pipeline skill" },
    @{ Name = "stackhawk-data-seed"; Catalog = "stackhawk-data-seed"; Folder = "stackhawk-data-seed"; Label = "Data seed skill" },
    @{ Name = "optimize";            Catalog = "stackhawk-optimize";  Folder = "optimize";            Label = "Scan optimization skill" }
)
$CursorRulesSource  = Join-Path $RepoRoot "cursor-plugins/hawkscan/rules"
$CursorHooksSource  = Join-Path $RepoRoot "cursor-plugins/hawkscan/hooks/cursor"
$CursorLegacyRules  = Join-Path $PSScriptRoot "cursor-legacy-rules.txt"
$CursorHookScript   = "stackhawk-stop.sh"
$CursorLegacyMarker = "# Cursor stop hook for hawkscan plugin"
$CursorProjectCmd   = ".cursor/hooks/$CursorHookScript"
$CursorUserCmd      = "./hooks/$CursorHookScript"

# The folder of one skill: plugins/<catalog name>/skills/<skill> in a released snapshot,
# plugins/<source folder>/skills/<skill> in a clone. $null if neither exists.
function Get-SkillSource($Skill) {
    foreach ($plugin in @($Skill.Catalog, $Skill.Folder)) {
        $dir = Join-Path (Join-Path (Join-Path (Join-Path $RepoRoot "plugins") $plugin) "skills") $Skill.Name
        if (Test-Path -LiteralPath (Join-Path $dir "SKILL.md") -PathType Leaf) { return $dir }
    }
    return $null
}

# Stops before any change if a skill of the list is missing from this checkout.
function Assert-SkillSources($Skills) {
    foreach ($skill in $Skills) {
        if ($null -eq (Get-SkillSource $skill)) {
            Fail "the $($skill.Name) skill was not found under $RepoRoot/plugins/$($skill.Catalog)/ or $RepoRoot/plugins/$($skill.Folder)/. Nothing was installed. Is the repository fully checked out?"
        }
    }
}

function Test-StackHawkSkill([string]$Dir, [string]$Name) {
    $skillMd = Join-Path $Dir "SKILL.md"
    if (-not (Test-Path -LiteralPath $skillMd -PathType Leaf)) { return $false }
    $text = Get-Content -Raw -Encoding UTF8 -LiteralPath $skillMd
    $nameLine = ($text -split "`n" | Where-Object { $_ -match '^name:' } | Select-Object -First 1)
    if ($null -eq $nameLine) { return $false }
    $found = ($nameLine -replace '^name:\s*', '').Trim()
    return ($found -ceq $Name) -and ($text -match '(?i)stackhawk|hawkscan')
}

function Read-HooksJson([string]$Path) {
    try {
        # -Encoding UTF8: Windows PowerShell 5.1 reads a file without a BOM as ANSI otherwise,
        # and the merge would write other hooks' non-ASCII paths back double-encoded.
        $data = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
    } catch {
        Fail "$Path cannot be updated: it is not valid JSON ($($_.Exception.Message)). Nothing was installed. Fix the file, then run the installer again."
    }
    if ($data -isnot [System.Management.Automation.PSCustomObject]) {
        Fail "$Path cannot be updated: its top level is not an object. Nothing was installed."
    }
    $hooks = $data.PSObject.Properties['hooks']
    if ($null -ne $hooks) {
        if ($hooks.Value -isnot [System.Management.Automation.PSCustomObject]) {
            Fail "${Path} cannot be updated: its `"hooks`" value is not an object. Nothing was installed."
        }
        $stop = $hooks.Value.PSObject.Properties['stop']
        if ($null -ne $stop -and $stop.Value -isnot [System.Array]) {
            Fail "${Path} cannot be updated: its `"hooks`".`"stop`" value is not a list. Nothing was installed."
        }
    }
    return $data
}

# A rule file is ours when its frontmatter description starts with "StackHawk".
function Test-StackHawkRule([string]$File) {
    $text = Get-Content -Raw -Encoding UTF8 -LiteralPath $File
    return $text -match '(?m)^description:[ \t]*StackHawk'
}

function Invoke-CursorPreflight([string]$DotCursor, [string]$Scope) {
    Assert-SkillSources $CursorSkills
    foreach ($skill in $CursorSkills) {
        $dir = Join-Path (Join-Path $DotCursor "skills") $skill.Name
        if ((Test-Path -LiteralPath $dir) -and -not (Test-StackHawkSkill $dir $skill.Name)) {
            Fail "$dir exists and is not the StackHawk $($skill.Name) skill. Nothing was installed. Move that folder away, then run the installer again."
        }
    }
    if ($Scope -eq "project") {
        foreach ($rule in Get-ChildItem -LiteralPath $CursorRulesSource -Filter "*.mdc") {
            $existing = Join-Path (Join-Path $DotCursor "rules") $rule.Name
            if ((Test-Path -LiteralPath $existing) -and -not (Test-StackHawkRule $existing)) {
                Fail "$existing exists and is not a StackHawk rule. Nothing was installed. Rename that rule, then run the installer again."
            }
        }
    }
    $hooksJson = Join-Path $DotCursor "hooks.json"
    if (Test-Path -LiteralPath $hooksJson) { Read-HooksJson $hooksJson | Out-Null }
}

function Install-CursorSkills([string]$DotCursor) {
    foreach ($skill in $CursorSkills) {
        $dest = Join-Path (Join-Path $DotCursor "skills") $skill.Name
        if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
        New-Item -ItemType Directory -Force $dest | Out-Null
        Copy-Item -Path (Join-Path (Get-SkillSource $skill) "*") -Destination $dest -Recurse -Force
    }
    Write-Host "Installed $($CursorSkills.Count) Cursor skills to $DotCursor/skills/"
    foreach ($skill in $CursorSkills) {
        Write-Host ("  {0,-24} - {1}" -f "$($skill.Name)/", $skill.Label)
    }
}

function Remove-CursorLegacyRules([string]$RulesDir) {
    $removed = 0
    if (-not (Test-Path -LiteralPath $RulesDir -PathType Container)) { return $removed }
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $CursorLegacyRules) {
        $name = $line.Trim()
        if ($name -eq "" -or $name.StartsWith("#")) { continue }
        $file = Join-Path $RulesDir $name
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            Remove-Item -LiteralPath $file -Force
            $removed++
        }
    }
    return $removed
}

function Install-CursorRules([string]$DotCursor, [string]$Scope) {
    $rulesDir = Join-Path $DotCursor "rules"
    $removed = Remove-CursorLegacyRules $rulesDir
    if ($Scope -eq "project") {
        New-Item -ItemType Directory -Force $rulesDir | Out-Null
        Copy-Item -Path (Join-Path $CursorRulesSource "*.mdc") -Destination $rulesDir -Force
        Write-Host "Installed 2 Cursor rules to $rulesDir/"
        Write-Host "  stackhawk.mdc            - always-applied router (names the skills and when each applies)"
        Write-Host "  stackhawk-config.mdc     - applies while stackhawk.yml is in context"
    } else {
        Write-Host "No rules installed: Cursor has no file-based user rules. For the router rule, use"
        Write-Host "project installs instead of this user-level install, not both: each adds a stop hook."
    }
    if ($removed -gt 0) {
        Write-Host ""
        Write-Host "WARNING: Removed $removed legacy StackHawk rules from $rulesDir/."
        Write-Host "  The generated rules in cursor/.cursor/rules/ are deprecated and are no longer installed:"
        Write-Host "  Cursor now loads the skills on demand and reads one small router rule."
        Write-Host "  cursor/ will be removed in the next major release."
    }
}

function Test-OurStopEntry($Item, [bool]$DropLegacy) {
    if ($Item -isnot [System.Management.Automation.PSCustomObject]) { return $false }
    $property = $Item.PSObject.Properties['command']
    if ($null -eq $property) { return $false }
    $command = ([string]$property.Value).Trim('"', "'", ' ')
    return $command.EndsWith("stackhawk-stop.sh") -or ($DropLegacy -and $command -eq ".cursor/hooks/stop.sh")
}

function Merge-CursorHooksJson([string]$Path, [string]$Command, [bool]$DropLegacy) {
    $data = Read-HooksJson $Path
    $template = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $CursorHooksSource "hooks.json") | ConvertFrom-Json
    $entry = [ordered]@{}
    foreach ($p in $template.hooks.stop[0].PSObject.Properties) { $entry[$p.Name] = $p.Value }
    $entry["command"] = $Command

    $out = [ordered]@{}
    if ($null -eq $data.PSObject.Properties['version']) { $out["version"] = 1 }
    foreach ($p in $data.PSObject.Properties) { $out[$p.Name] = $p.Value }
    $hooks = [ordered]@{}
    if ($null -ne $data.PSObject.Properties['hooks']) {
        foreach ($p in $data.hooks.PSObject.Properties) { $hooks[$p.Name] = $p.Value }
    }
    $kept = @()
    if ($hooks.Contains("stop")) {
        $kept = @($hooks["stop"] | Where-Object { -not (Test-OurStopEntry $_ $DropLegacy) })
    }
    $hooks["stop"] = @($kept) + @($entry)
    $out["hooks"] = $hooks
    Write-Utf8NoBom $Path ((ConvertTo-Json -InputObject $out -Depth 20) + "`n")
}

function Install-CursorHook([string]$DotCursor, [string]$Scope) {
    $command = if ($Scope -eq "user") { $CursorUserCmd } else { $CursorProjectCmd }
    $hooksDir = Join-Path $DotCursor "hooks"
    $script = Join-Path $hooksDir $CursorHookScript
    $legacy = Join-Path $hooksDir "stop.sh"
    $hooksJson = Join-Path $DotCursor "hooks.json"
    New-Item -ItemType Directory -Force $hooksDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $CursorHooksSource "stop.sh") -Destination $script -Force
    if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) { & chmod +x $script }
    $dropLegacy = (Test-Path -LiteralPath $legacy -PathType Leaf) -and
        [bool](Select-String -LiteralPath $legacy -SimpleMatch -Pattern $CursorLegacyMarker -Quiet)

    if (Test-Path -LiteralPath $hooksJson) {
        Merge-CursorHooksJson $hooksJson $command $dropLegacy
    } else {
        $text = (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $CursorHooksSource "hooks.json")).Replace($CursorProjectCmd, $command)
        Write-Utf8NoBom $hooksJson $text
    }
    if ($dropLegacy) {
        Remove-Item -LiteralPath $legacy -Force
        Write-Host "Removed the old StackHawk hook $legacy and its hooks.json entry."
    }
    Write-Host "Installed the Cursor stop hook to $DotCursor/"
    Write-Host "  hooks/$CursorHookScript  - asks for a scan when a turn changed code without one (once per conversation)"
    Write-Host "  hooks.json               - one stop entry ($command); other entries are kept"
}

function Install-Cursor {
    $dotCursor = Join-Path $TargetPath ".cursor"
    $scope = "project"
    if ((Test-Path -LiteralPath $HOME -PathType Container) -and ((Get-PhysicalPath $TargetPath) -eq (Get-PhysicalPath $HOME))) {
        $scope = "user"
    }
    $required = @($CursorLegacyRules, (Join-Path $CursorHooksSource "stop.sh"), (Join-Path $CursorHooksSource "hooks.json"),
        (Join-Path $CursorRulesSource "stackhawk.mdc"), (Join-Path $CursorRulesSource "stackhawk-config.mdc"))
    foreach ($file in $required) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            Fail "$file not found. Is the repository fully checked out?"
        }
    }
    Invoke-CursorPreflight $dotCursor $scope
    Write-Host "Installing StackHawk for Cursor ($scope level) into $dotCursor/"
    Write-Host ""
    Install-CursorSkills $dotCursor
    Install-CursorRules $dotCursor $scope
    Install-CursorHook $dotCursor $scope
}

switch ($Platform) {
    "cursor" {
        Install-Cursor
    }

    "copilot" {
        $copilotSkills = @(
            @{ Name = "hawkscan"; Catalog = "hawkscan";      Folder = "hawkscan" },
            @{ Name = "api";      Catalog = "stackhawk-api"; Folder = "api" }
        )
        Assert-SkillSources $copilotSkills
        $hawkscanSrc = Get-SkillSource $copilotSkills[0]
        $apiSrc      = Get-SkillSource $copilotSkills[1]
        $dest        = Join-Path (Join-Path $TargetPath ".agents") "skills"
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
        Copy-Item -Recurse (Join-Path $hawkscanSrc "*") $hawkscanDst -Force
        Copy-Item -Recurse (Join-Path $apiSrc "*")      $apiDst      -Force
        Write-Host "Installed StackHawk skills to ${dest}\"
        Write-Host "  hawkscan\       -- DAST scanning skill"
        Write-Host "  stackhawk-api\  -- API reporting skill"
    }
}
