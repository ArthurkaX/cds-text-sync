# Set encoding to UTF8 for correct character display
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoUrl = "https://github.com/ArthurkaX/cds-text-sync"
$targetBaseDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
$repoName = "cds-text-sync"
# ScriptDir gets generated menu stubs only; the tool itself goes to $bodyPath.
$menuDir = Join-Path $targetBaseDir $repoName
$bodyPath = Join-Path $env:LOCALAPPDATA $repoName

# Rehearsal mode. Set $env:CTS_SETUP_DRYRUN before running to walk every branch
# -- migration, replace, PATH, menu -- without changing anything outside $env:TEMP.
# The name has to be true: this used to guard only the migration moves while the
# body tree was still deleted and replaced, the CLI PATH still changed, and the stubs were
# still written, so a "rehearsal" performed a real install.
$dryRun = -not [string]::IsNullOrWhiteSpace($env:CTS_SETUP_DRYRUN)

Write-Host "--- Environment Setup: cds-text-sync ---" -ForegroundColor Cyan

if ($dryRun) {
    Write-Host "[*] DRY RUN: no changes will be made to your system." -ForegroundColor Magenta
}

# Windows PowerShell draws a progress bar per received chunk: downloads and
# Expand-Archive run many times slower, and fail where there is no console to
# draw it on. The function scope keeps the caller's preference, which
# `irm | iex` would otherwise change.
function Save-Url {
    param([string]$Uri, [string]$OutFile)
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Install-CliCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallPath
    )

    $cliDir = Join-Path $InstallPath "products\codesys-agent\dist"
    $ctsExe = Join-Path $cliDir "cts.exe"
    Write-Host "`n--- CLI Installation ---" -ForegroundColor Cyan
    Write-Host "Add the bundled cts.exe folder to your user PATH?"
    Write-Host "This lets new terminals run: cts --help" -ForegroundColor Green
    $cliChoice = Read-Host "`nAdd to user PATH [Y, N] (default: Y)"
    if ([string]::IsNullOrWhiteSpace($cliChoice)) { $cliChoice = "Y" }

    if ($cliChoice.ToUpperInvariant() -eq "Y") {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $normalizePath = { param($value) ([string]$value).Trim().TrimEnd('\') }
        $alreadyPresent = @($userPath -split ';' | Where-Object {
            [string]::Equals((& $normalizePath $_), (& $normalizePath $cliDir), [StringComparison]::OrdinalIgnoreCase)
        }).Count -gt 0
        if ($alreadyPresent) {
            Write-Host "[*] The cts.exe folder is already on your user PATH." -ForegroundColor DarkGray
        } elseif ($dryRun) {
            Write-Host "[*] Dry run: would add $cliDir to the user PATH" -ForegroundColor Magenta
        } else {
            $newUserPath = if ([string]::IsNullOrWhiteSpace($userPath)) { $cliDir } else { "$userPath;$cliDir" }
            [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        }

        if (@($env:Path -split ';' | Where-Object {
            [string]::Equals((& $normalizePath $_), (& $normalizePath $cliDir), [StringComparison]::OrdinalIgnoreCase)
        }).Count -eq 0) {
            if ($dryRun) {
                Write-Host "[*] Dry run: would prepend $cliDir to this session's PATH" -ForegroundColor Magenta
            } else {
                $env:Path = "$cliDir;$env:Path"
            }
        }
    } else {
        Write-Host "[*] Skipping user PATH update. Run $ctsExe directly when needed." -ForegroundColor Yellow
    }

    # Old pip launchers can shadow the bundled executable. Only offer removal
    # when the old package is positively identified.
    $distCts = [System.IO.Path]::GetFullPath($ctsExe)
    $shadowing = @(Get-Command cts -All -ErrorAction SilentlyContinue | Where-Object {
        $_.Source -and -not [string]::Equals([System.IO.Path]::GetFullPath($_.Source), $distCts, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($shadowing.Count -gt 0) {
        $shadowPaths = @($shadowing | ForEach-Object { $_.Source } | Select-Object -Unique)
        foreach ($shadowPath in $shadowPaths) {
            Write-Host "[!] An older cts command may shadow the bundled CLI: $shadowPath" -ForegroundColor Yellow
        }
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { return }
        & python -m pip show cds-text-sync 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return }
        if ($dryRun) {
            Write-Host "[*] Dry run: would offer python -m pip uninstall -y cds-text-sync cds-cli" -ForegroundColor Magenta
            return
        }
        $removeChoice = Read-Host "Remove the old CLI packages? [Y, N] (default: Y)"
        if ([string]::IsNullOrWhiteSpace($removeChoice)) { $removeChoice = "Y" }
        if ($removeChoice.ToUpperInvariant() -eq "Y") {
            & python -m pip uninstall -y cds-text-sync cds-cli
        }
    }
    if ($dryRun) { return }
}

function Get-CodesysSpVersions {
    # Return the sorted, unique SP minor numbers (the N in 3.5.N.x) of every
    # CODESYS installation found under Program Files. Vendor forks (DIAStudio,
    # KeStudio, ...) use their own folder names and are intentionally not
    # detected here - those rely on the custom path option.
    $roots = @()
    if ($env:ProgramFiles) { $roots += $env:ProgramFiles }
    if (${env:ProgramFiles(x86)}) { $roots += ${env:ProgramFiles(x86)} }

    $sps = @()
    foreach ($root in $roots) {
        $dirs = Get-ChildItem -Path $root -Directory -Filter "CODESYS *" -ErrorAction SilentlyContinue
        foreach ($dir in $dirs) {
            if ($dir.Name -match "CODESYS\s+3\.5\.(\d+)(?:\.|$)") {
                $sps += [int]$matches[1]
            }
        }
    }
    return @($sps | Sort-Object -Unique)
}

function Resolve-ScriptDirDefault {
    # Pick a recommended ScriptDir based on the installed CODESYS versions.
    # Older CODESYS scans the machine-wide %PROGRAMDATA%\CODESYS\ScriptDir,
    # newer versions scan the per-user %LOCALAPPDATA%\CODESYS\ScriptDir. The
    # boundary is only used to pre-select a default; the user can always
    # override it in the menu, so an imperfect boundary is recoverable.
    param([int]$LegacyBoundary = 17)

    $sps = @(Get-CodesysSpVersions)
    $legacy = @($sps | Where-Object { $_ -lt $LegacyBoundary })
    $modern = @($sps | Where-Object { $_ -ge $LegacyBoundary })

    $recommended = "LocalAppData"
    $reason = ""

    if ($legacy.Count -gt 0 -and $modern.Count -eq 0) {
        $recommended = "ProgramData"
        $reason = "Only legacy CODESYS (SP < $LegacyBoundary) detected - the machine-wide ProgramData path is required."
    } elseif ($modern.Count -gt 0 -and $legacy.Count -eq 0) {
        $recommended = "LocalAppData"
        $reason = "Modern CODESYS (SP >= $LegacyBoundary) detected - the per-user ScriptDir is used."
    } elseif ($legacy.Count -gt 0 -and $modern.Count -gt 0) {
        $recommended = "LocalAppData"
        $reason = "Both legacy and modern CODESYS detected - the user path, and the menu goes to the machine-wide ProgramData path too, which only the legacy one reads."
    } else {
        $laExists = Test-Path (Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir")
        $pdExists = Test-Path (Join-Path $env:ProgramData "CODESYS\ScriptDir")
        if ($pdExists -and -not $laExists) {
            $recommended = "ProgramData"
            $reason = "No CODESYS version detected, but a legacy ProgramData ScriptDir already exists."
        } else {
            $recommended = "LocalAppData"
            $reason = "No CODESYS installation detected - using the standard user path."
        }
    }

    return [PSCustomObject]@{
        Versions       = $sps
        LegacyDetected = ($legacy.Count -gt 0)
        ModernDetected = ($modern.Count -gt 0)
        Recommended    = $recommended
        Reason         = $reason
    }
}

# The sync folder is a git repository: setting it runs `git init` there.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "`n[!] Git was not found. cds-text-sync keeps each project's sync folder as a git repository." -ForegroundColor Yellow
    Write-Host "[W] Install with winget" -ForegroundColor Green
    Write-Host "[M] Open manual download page" -ForegroundColor Green
    Write-Host "[S] Skip for now and continue anyway" -ForegroundColor Green
    $gitChoice = Read-Host "`nSelect option [W, M, S] (default: W)"
    if ([string]::IsNullOrWhiteSpace($gitChoice)) {
        $gitChoice = "W"
    }
    switch ($gitChoice.ToUpperInvariant()) {
        "W" {
            if (Get-Command winget -ErrorAction SilentlyContinue) {
                Write-Host "[*] Installing Git with winget..." -ForegroundColor Cyan
                $proc = Start-Process -FilePath "winget" -ArgumentList @("install", "-e", "--id", "Git.Git", "--accept-package-agreements", "--accept-source-agreements") -Wait -PassThru
                if ($proc.ExitCode -eq 0) {
                    Write-Host "[+] Git installed. Open a new PowerShell window before using cts." -ForegroundColor Green
                } else {
                    Write-Host "[!] winget install failed with exit code $($proc.ExitCode). Install Git from https://git-scm.com/download/win" -ForegroundColor Red
                }
            } else {
                Write-Host "[!] winget was not found on this machine; opening the download page." -ForegroundColor Yellow
                Start-Process "https://git-scm.com/download/win"
            }
        }
        "M" {
            Start-Process "https://git-scm.com/download/win"
        }
        default {
            Write-Host "[*] Skipping Git. cts will refuse to set a sync folder until git is installed." -ForegroundColor Yellow
        }
    }
}

# 2-4. The version: a named branch, or one picked from the menu. A branch
# is a test line shared before a release, installed without the menu:
#   $env:CTS_BRANCH = "next"; irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/next/irm/setup.ps1 | iex
# A build handed over as a file, for a PC without access to GitHub or a line
# not published there, installs from that archive (install.cmd beside it sets this):
#   $env:CTS_ARCHIVE = "C:\Users\me\Downloads\cds-text-sync-nightly-1a2b3c4d.zip"; .\setup.ps1
$archive = ([string]$env:CTS_ARCHIVE).Trim()
$branch = ([string]$env:CTS_BRANCH).Trim()
$zipUrl = ""
$fallbackZipUrl = ""
$versionName = ""
if ($archive) {
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        Write-Host "[!] CTS_ARCHIVE '$archive' is not a file." -ForegroundColor Red
        return
    }
    $archiveItem = Get-Item -LiteralPath $archive
    Write-Host "`n[*] Installing from the archive $($archiveItem.FullName) (CTS_ARCHIVE); clear it for the version menu." -ForegroundColor Cyan
    $zipUrl = ([Uri]$archiveItem.FullName).AbsoluteUri
    $versionName = [IO.Path]::GetFileNameWithoutExtension($archiveItem.Name)
} elseif ($branch) {
    if ($branch -notmatch '^[A-Za-z0-9._-]+$') {
        Write-Host "[!] CTS_BRANCH '$branch' is not a branch name this installer takes (letters, digits, . _ -)." -ForegroundColor Red
        return
    }
    Write-Host "`n[*] Installing branch $branch (CTS_BRANCH); clear it for the version menu." -ForegroundColor Cyan
    $zipUrl = "$repoUrl/archive/refs/heads/$branch.zip"
    $versionName = $branch
} else {
    # 2. Get available releases
    Write-Host "`n[*] Fetching available versions..." -ForegroundColor Cyan
    $stableTags = @()
    $testTags = @()
    try {
        $releasesUrl = "https://api.github.com/repos/ArthurkaX/cds-text-sync/releases?per_page=100"
        $headers = @{
            "User-Agent" = "cds-text-sync-setup"
            "Accept" = "application/vnd.github+json"
        }
        $releases = Invoke-RestMethod -Uri $releasesUrl -Headers $headers -Method Get
        if ($releases) {
            foreach ($release in $releases) {
                $tag = [string]$release.tag_name
                $isPrerelease = [bool]$release.prerelease

                if ($isPrerelease -or $tag -match "^v\d+\.\d+\.\d+-test\.\d+$") {
                    $testTags += $tag
                } elseif ($tag -match "^v\d+\.\d+\.\d+$") {
                    $stableTags += $tag
                }
            }

            $stableTags = @($stableTags | Select-Object -Unique)
            $testTags = @($testTags | Select-Object -Unique)

            if ($stableTags.Count -gt 5) {
                $stableTags = @($stableTags | Select-Object -First 5)
            }
            if ($testTags.Count -gt 5) {
                $testTags = @($testTags | Select-Object -First 5)
            }
        }
    } catch {
        try {
            $tagsUrl = "$repoUrl/tags"
            $tagsResponse = Invoke-WebRequest -Uri $tagsUrl -UseBasicParsing
            if ($tagsResponse.StatusCode -eq 200) {
                # Parse tags from HTML - look for stable and prerelease tags
                $stableTags = @($tagsResponse.Content | Select-String "v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?" |
                    ForEach-Object {
                        $line = $_.ToString()
                        if ($line -match "v(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)") {
                            "v" + $matches[1]
                        }
                    } |
                    Where-Object { $_ -ne $null } |
                    Select-Object -Unique)

                $stableTags = @($stableTags | Where-Object { $_ -match "^v\d+\.\d+\.\d+$" })
                $testTags = @($tagsResponse.Content | Select-String "v\d+\.\d+\.\d+-test\.\d+" |
                    ForEach-Object {
                        $line = $_.ToString()
                        if ($line -match "(v\d+\.\d+\.\d+-test\.\d+)") {
                            $matches[1]
                        }
                    } |
                    Where-Object { $_ -ne $null } |
                    Select-Object -Unique)

                if ($stableTags.Count -gt 5) {
                    $stableTags = @($stableTags | Select-Object -Last 5)
                }
                if ($testTags.Count -gt 5) {
                    $testTags = @($testTags | Select-Object -Last 5)
                }
            }
        } catch {
            Write-Host "[!] Warning: Could not fetch releases. Only main branch will be available." -ForegroundColor Yellow
        }
    }

    # 3. Show version selection menu
    Write-Host "`n--- Version Selection ---" -ForegroundColor Cyan
    Write-Host "[L] 4.x, the latest (main branch) [DEFAULT]" -ForegroundColor Green

    if ($stableTags.Count -gt 0) {
        Write-Host "Stable Releases (last $($stableTags.Count)):" -ForegroundColor Cyan
        for ($i = 0; $i -lt $stableTags.Count; $i++) {
            $tag = $stableTags[$i]
            $isLatest = ($i -eq 0)
            $label = if ($isLatest) { " (latest stable)" } else { "" }
            Write-Host "[$($i+1)] $tag$label" -ForegroundColor Yellow
        }
    }

    if ($testTags.Count -gt 0) {
        Write-Host "Test / Pre-release Builds (last $($testTags.Count)):" -ForegroundColor Cyan
        for ($i = 0; $i -lt $testTags.Count; $i++) {
            $tag = $testTags[$i]
            $isLatest = ($i -eq 0)
            $label = if ($isLatest) { " (latest tagged pre-release)" } else { "" }
            Write-Host "[T$($i+1)] $tag$label" -ForegroundColor Yellow
        }
    }

    $stableRange = if ($stableTags.Count -gt 0) { "1-$($stableTags.Count)" } else { "none" }
    $testRange = if ($testTags.Count -gt 0) { "T1-T$($testTags.Count)" } else { "none" }
    $choice = Read-Host "`nSelect version [L, $stableRange, $testRange] (default: L)"
    if ([string]::IsNullOrWhiteSpace($choice)) {
        $choice = "L"
    }

    # 4. Determine download URL and version name

    if ($choice -eq "L") {
        $zipUrl = "$repoUrl/archive/refs/heads/main.zip"
        $versionName = "main"
    } elseif ($choice -match '^[Tt](\d+)$') {
        $testIndex = [int]$matches[1] - 1
        if ($testIndex -ge 0 -and $testIndex -lt $testTags.Count) {
            $selectedTag = $testTags[$testIndex]
            $zipUrl = "$repoUrl/releases/download/$selectedTag/cds-text-sync-$selectedTag.zip"
            $fallbackZipUrl = "$repoUrl/archive/refs/tags/$selectedTag.zip"
            $versionName = $selectedTag
        } else {
            Write-Host "[!] Invalid selection. Falling back to main branch." -ForegroundColor Yellow
            $zipUrl = "$repoUrl/archive/refs/heads/main.zip"
            $versionName = "main"
        }
    } else {
        $tagIndex = [int]$choice - 1
        if ($tagIndex -ge 0 -and $tagIndex -lt $stableTags.Count) {
            $selectedTag = $stableTags[$tagIndex]
            $zipUrl = "$repoUrl/releases/download/$selectedTag/cds-text-sync-$selectedTag.zip"
            $fallbackZipUrl = "$repoUrl/archive/refs/tags/$selectedTag.zip"
            $versionName = $selectedTag
        } else {
            Write-Host "[!] Invalid selection. Falling back to main branch." -ForegroundColor Yellow
            $zipUrl = "$repoUrl/archive/refs/heads/main.zip"
            $versionName = "main"
        }
    }

    # Releases up to 3.4.1 have no cts.exe, nor has main while it carries
    # them (no products/codesys-agent there): their own installer sets them up.
    $beforeCtsExe = $false
    if ($versionName -match '^v(\d+)\.(\d+)\.(\d+)') {
        $beforeCtsExe = [version]"$($matches[1]).$($matches[2]).$($matches[3])" -le [version]"3.4.1"
    } elseif ($versionName -eq "main") {
        try { Invoke-WebRequest -Uri "https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/products/codesys-agent/Directory.Build.props" -Method Head -UseBasicParsing | Out-Null }
        catch { $beforeCtsExe = $_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404 }
    }
    if ($beforeCtsExe) {
        $ownInstaller = "https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/$versionName/irm/setup.ps1"
        $pickAgain = if ($versionName -eq "main") { "L (main)" } else { $versionName }
        Write-Host "`n[*] $versionName comes before cts.exe; its own installer sets it up. Pick $pickAgain again in its menu." -ForegroundColor Cyan
        # The agent this line put beside the menu entry is nothing to the older
        # menu, whose installer refuses a folder it does not know.
        $agentDirs = @("CODESYS\ScriptDir", "Astra.IDE\ScriptDir") | ForEach-Object { Join-Path (Join-Path $env:LOCALAPPDATA $_) "cds-text-sync\agent" }
        $agentDirs += Join-Path $env:ProgramData "CODESYS\ScriptDir\cds-text-sync\agent"
        if ($dryRun) {
            foreach ($agentDir in $agentDirs | Where-Object { Test-Path -LiteralPath $_ }) { Write-Host "[*] Dry run: would remove $agentDir" -ForegroundColor Magenta }
            Write-Host "[*] Dry run: would run $ownInstaller" -ForegroundColor Magenta
        }
        if (-not $dryRun) {
            foreach ($agentDir in $agentDirs | Where-Object { Test-Path -LiteralPath $_ }) {
                try { Remove-Item -LiteralPath $agentDir -Recurse -Force -ErrorAction Stop }
                catch {
                    Write-Host "[!] Could not remove $agentDir ($_): close CODESYS and run the installer again." -ForegroundColor Red
                    return
                }
            }
            # The older installer replaces its program folder, which holds this
            # PC's projects.json (each project's sync folder and the PC's role),
            # without it; an update back to this line reads it again.
            $registry = Join-Path $env:LOCALAPPDATA "cds-text-sync\projects.json"
            $registryBytes = if (Test-Path -LiteralPath $registry) { [IO.File]::ReadAllBytes($registry) } else { $null }
            Invoke-Expression (Invoke-RestMethod -Uri $ownInstaller -UseBasicParsing)
            if ($registryBytes -and (Test-Path -LiteralPath (Split-Path $registry)) -and -not (Test-Path -LiteralPath $registry)) {
                [IO.File]::WriteAllBytes($registry, $registryBytes)
                Write-Host "[+] Kept projects.json for a later update." -ForegroundColor Green
            }
        }
        return
    }
}

# 5. Installation Path Selection
$recommendation = Resolve-ScriptDirDefault
$localAppDataScriptDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
$programDataScriptDir  = Join-Path $env:ProgramData "CODESYS\ScriptDir"
$targetIsProgramData = $false

Write-Host "`n--- Installation Path ---" -ForegroundColor Cyan
if ($recommendation.Versions.Count -gt 0) {
    Write-Host ("[i] Detected CODESYS: " + (($recommendation.Versions | ForEach-Object { "3.5.$_" }) -join ", ")) -ForegroundColor DarkGray
}
if ($recommendation.Reason) {
    Write-Host "[i] $($recommendation.Reason)" -ForegroundColor DarkGray
}

$laLabel = if ($recommendation.Recommended -eq "LocalAppData") { " [RECOMMENDED]" } else { "" }
$pdLabel = if ($recommendation.Recommended -eq "ProgramData") { " [RECOMMENDED]" } else { "" }

Write-Host "[1] Standard CODESYS user path (%LOCALAPPDATA%\CODESYS\ScriptDir\)$laLabel"
Write-Host "[2] Alternative path (for KeStudio, DIA Designer-AX, custom forks)"
Write-Host "[3] Legacy CODESYS < 3.5.17 (%PROGRAMDATA%\CODESYS\ScriptDir\)$pdLabel"

$defaultChoice = if ($recommendation.Recommended -eq "ProgramData") { "3" } else { "1" }
$pathChoice = Read-Host "`nSelect installation path [1, 2, 3] (default: $defaultChoice)"
if ([string]::IsNullOrWhiteSpace($pathChoice)) {
    $pathChoice = $defaultChoice
}

if ($pathChoice -eq "2") {
    Write-Host "`n[*] To copy the path:" -ForegroundColor Cyan
    Write-Host "    1. Navigate to your ScriptDir folder in File Explorer"
    Write-Host "    2. Hold Shift and right-click the folder"
    Write-Host "    3. Select 'Copy as path'"
    Write-Host "`nFor more details, see: https://github.com/ArthurkaX/cds-text-sync/blob/main/docs/alternative-installations.md" -ForegroundColor Yellow

    $targetBaseDir = Read-Host "`nEnter the full path to ScriptDir"

    # Remove quotes from path if present
    $targetBaseDir = $targetBaseDir.Trim('"', "'")

    # Validate path - create parent directories if needed
    if (-not (Test-Path $targetBaseDir)) {
        if ($dryRun) {
            Write-Host "[*] Dry run: would create directory $targetBaseDir" -ForegroundColor Magenta
        } else {
            Write-Host "[*] Directory does not exist. Creating: $targetBaseDir" -ForegroundColor Yellow
            try {
                New-Item -ItemType Directory -Force -Path $targetBaseDir -ErrorAction Stop | Out-Null
                Write-Host "[+] Directory created successfully." -ForegroundColor Green
            } catch {
                Write-Host "[!] Failed to create directory: $_" -ForegroundColor Red
                Write-Host "[*] Falling back to standard path..." -ForegroundColor Yellow
                $targetBaseDir = $localAppDataScriptDir
            }
        }
    }
} elseif ($pathChoice -eq "3") {
    $targetBaseDir = $programDataScriptDir
    $targetIsProgramData = $true
    Write-Host "[*] Using legacy machine-wide path: $targetBaseDir" -ForegroundColor Cyan
} else {
    $targetBaseDir = $localAppDataScriptDir
}

# The menu directory holds nothing but generated cds-text-sync.py stub.
# The tool itself goes to $bodyPath, chosen a few lines below.
$menuDir = Join-Path $targetBaseDir $repoName

# 5b. If installing into ProgramData, verify write access up front.
# %PROGRAMDATA%\CODESYS usually needs administrator rights. On failure we warn,
# print the exact elevated copy command, and fall back to the user path so the
# tool and CLI are still installed (the legacy CODESYS only sees the scripts once
# they are copied into ProgramData).
if ($targetIsProgramData) {
    $canWriteProgramData = $false
    if ($dryRun) {
        # Probing means creating the folder and writing a file into ProgramData.
        # Both are outside %TEMP%, so a rehearsal reports the gap instead.
        Write-Host "[*] Dry run: skipping the ProgramData write probe" -ForegroundColor Magenta
        $canWriteProgramData = $true
    } else {
        try {
            if (-not (Test-Path $targetBaseDir)) {
                New-Item -ItemType Directory -Force -Path $targetBaseDir -ErrorAction Stop | Out-Null
            }
            $probeFile = Join-Path $targetBaseDir (".cts_write_test_" + $PID)
            Set-Content -Path $probeFile -Value "test" -ErrorAction Stop
            Remove-Item -Path $probeFile -Force -ErrorAction SilentlyContinue
            $canWriteProgramData = $true
        } catch {
            $canWriteProgramData = $false
        }
    }

    if (-not $canWriteProgramData) {
        Write-Host "`n[!] No write permission for the legacy ProgramData ScriptDir:" -ForegroundColor Yellow
        Write-Host "    $targetBaseDir" -ForegroundColor Yellow
        Write-Host "    This path typically requires administrator rights." -ForegroundColor Yellow
        Write-Host "`n    Fix option A - re-run this installer from an elevated PowerShell (Run as administrator)." -ForegroundColor Cyan
        Write-Host "    Fix option B - after this run, copy the generated menu scripts once from an elevated PowerShell:" -ForegroundColor Cyan
        Write-Host "        Copy-Item -Recurse -Force `"$localAppDataScriptDir\$repoName`" `"$targetBaseDir\`"" -ForegroundColor Cyan
        Write-Host "`n[*] Falling back to the standard user path so the tool and CLI are still installed:" -ForegroundColor Yellow
        Write-Host "    $localAppDataScriptDir" -ForegroundColor Yellow
        Write-Host "    (On legacy CODESYS the scripts appear only after they exist in ProgramData.)" -ForegroundColor Yellow
        $targetBaseDir = $localAppDataScriptDir
        $targetIsProgramData = $false
        $menuDir = Join-Path $targetBaseDir $repoName
    }
}

# 5c. Program location (the "body").
#
# CODESYS scans ScriptDir recursively and lists every .py it finds, so the tool
# itself must not live there: otherwise ~120 internal modules end up in the
# Tools > Scripting menu. ScriptDir receives nothing but generated cds-text-sync.py
# stubs; everything else is installed here.
$defaultBodyPath = Join-Path $env:LOCALAPPDATA $repoName
$bodyPath = $defaultBodyPath

Write-Host "`n--- Program Location ---" -ForegroundColor Cyan
Write-Host "Only the generated menu scripts go into ScriptDir. The tool itself is installed to:"
Write-Host "[1] $defaultBodyPath  [RECOMMENDED]"
Write-Host "[2] Another folder (for example an existing git clone)"

$bodyChoice = Read-Host "`nSelect program location [1, 2] (default: 1)"
if ($bodyChoice -eq "2") {
    $enteredBody = Read-Host "Enter the full path for the program folder"
    $enteredBody = $enteredBody.Trim('"', "'")
    if (-not [string]::IsNullOrWhiteSpace($enteredBody)) {
        $bodyPath = $enteredBody
    }
}

# Refuse a body inside any ScriptDir - the scanner would still walk all of it.
$bodyProbe = $bodyPath
$bodyInsideScriptDir = $false
while (-not [string]::IsNullOrWhiteSpace($bodyProbe)) {
    if ((Split-Path $bodyProbe -Leaf) -ieq "ScriptDir") { $bodyInsideScriptDir = $true; break }
    $probeParent = Split-Path $bodyProbe -Parent
    if ([string]::IsNullOrWhiteSpace($probeParent) -or $probeParent -eq $bodyProbe) { break }
    $bodyProbe = $probeParent
}
if ($bodyInsideScriptDir) {
    Write-Host "[!] That folder is inside a CODESYS ScriptDir, which defeats the purpose." -ForegroundColor Yellow
    Write-Host "[*] Using the standard location instead: $defaultBodyPath" -ForegroundColor Yellow
    $bodyPath = $defaultBodyPath
}

# 5d. Migrate an existing flat installation out of ScriptDir.
$migrated = $false
if (Test-Path -LiteralPath $menuDir) {
    $menuItem = Get-Item -LiteralPath $menuDir -Force
    $isLink = [bool]($menuItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)

    # The layouts cts install leaves to this installer. Older releases
    # used src\ide_bridge at the menu root; newer archives have the bridge under
    # products\codesys-host and carry the root cds_text_sync package instead.
    $isFullInstallation = (
        (Test-Path (Join-Path $menuDir "src\ide_bridge")) -or
        (Test-Path (Join-Path $menuDir "products\codesys-host\src\ide_bridge")) -or
        (Test-Path (Join-Path $menuDir "cds_text_sync")) -or
        (Test-Path (Join-Path $menuDir "cli")) -or
        (Test-Path (Join-Path $menuDir ".git"))
    )

    if ($isLink -or $isFullInstallation) {
        if ($dryRun) {
            Write-Host "[*] Dry run: would ask before migrating the existing installation in $menuDir" -ForegroundColor Magenta
        } else {
            $migrationChoice = Read-Host "`nFound an older full installation in $menuDir. Move it to the program folder now? [Y/N] (default: Y)"
            if ([string]::IsNullOrWhiteSpace($migrationChoice)) {
                $migrationChoice = "Y"
            }
            if ($migrationChoice.ToUpperInvariant() -ne "Y") {
                throw "Migration cancelled. Move or delete $menuDir manually, then run the installer again."
            }
        }
    }

    if ($isLink) {
        # A developer symlink or junction. Its target is the user's own working
        # copy - never touch it. Delete the link itself only: Remove-Item
        # -Recurse follows reparse points on Windows PowerShell 5.1 and would
        # wipe the target's contents.
        $linkTarget = $menuItem.Target
        if ($linkTarget -is [array]) { $linkTarget = $linkTarget[0] }
        Write-Host "`n[*] ScriptDir holds a link to: $linkTarget" -ForegroundColor Cyan
        Write-Host "[*] Removing the link only; its target is left untouched." -ForegroundColor Cyan
        if ($bodyChoice -ne "2" -and -not [string]::IsNullOrWhiteSpace($linkTarget)) {
            $bodyPath = $linkTarget
        }
        if (-not $dryRun) {
            [System.IO.Directory]::Delete($menuDir, $false)
        }
        $migrated = $true
    }
    elseif ($isFullInstallation) {
        Write-Host "`n[*] Found a full installation inside ScriptDir. Moving it out to:" -ForegroundColor Cyan
        Write-Host "    $bodyPath" -ForegroundColor Cyan
        if (Test-Path -LiteralPath $bodyPath) {
            $asidePath = "$bodyPath.pre-migration"
            Write-Host "[!] $bodyPath already exists; moving it aside to $asidePath" -ForegroundColor Yellow
            if (-not $dryRun) {
                if (Test-Path -LiteralPath $asidePath) {
                    Remove-Item -LiteralPath $asidePath -Recurse -Force
                }
                Move-Item -LiteralPath $bodyPath -Destination $asidePath
            }
        }
        # Move, never copy-then-delete: projects.json and other untracked
        # user files live inside the tree, and a git clone keeps its remote.
        if (-not $dryRun) {
            Move-Item -LiteralPath $menuDir -Destination $bodyPath
        }
        $migrated = $true
    }
}

# One-off cleanup: older installers left a full backup tree inside ScriptDir,
# which doubled the menu pollution for everyone who ever updated.
$legacyBackup = "$menuDir.backup"
if (Test-Path -LiteralPath $legacyBackup) {
    Write-Host "[*] Removing the old backup left inside ScriptDir: $legacyBackup" -ForegroundColor Cyan
    if (-not $dryRun) {
        Remove-Item -LiteralPath $legacyBackup -Recurse -Force
    }
}

Write-Host "[*] Program folder: $bodyPath" -ForegroundColor Cyan

# 6. Create required directories if they don't exist
if (-not (Test-Path $targetBaseDir)) {
    if ($dryRun) {
        Write-Host "[*] Dry run: would create directory $targetBaseDir" -ForegroundColor Magenta
    } else {
        Write-Host "[*] Creating directory: $targetBaseDir" -ForegroundColor Cyan
        New-Item -ItemType Directory -Force -Path $targetBaseDir | Out-Null
    }
}

# 6. Download and install
# A branch moves, and GitHub's CDN keeps what a URL answered for minutes, so a
# branch is fetched by the commit it points at now: the archive and the agent
# binaries then come from the same commit.
$mediaRef = $versionName
if ($zipUrl -like "*/archive/refs/heads/*") {
    try {
        $commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/ArthurkaX/cds-text-sync/commits/$versionName" -UseBasicParsing).sha
        if ($commit -match '^[0-9a-f]{40}$') {
            $zipUrl = "$repoUrl/archive/$commit.zip"
            $mediaRef = $commit
            Write-Host "[*] Branch $versionName is at commit $($commit.Substring(0, 8))." -ForegroundColor Cyan
        }
    } catch {
        Write-Host "[!] Could not look up the commit of $versionName ($_); downloading the branch by name." -ForegroundColor Yellow
    }
}
$tempZipPath = "$env:TEMP\cds-text-sync-$versionName.zip"
$tempExtractPath = "$env:TEMP\cds-text-sync-temp-$versionName"

try {
    $fetching = if ($archive) { "Reading the archive" } else { "Downloading cds-text-sync" }
    Write-Host "[*] $fetching ($versionName)..." -ForegroundColor Cyan
    try {
        Save-Url $zipUrl $tempZipPath
    } catch {
        if ($fallbackZipUrl) {
            Write-Host "[!] Release asset not available; downloading source archive for $versionName instead." -ForegroundColor Yellow
            Save-Url $fallbackZipUrl $tempZipPath
        } else {
            throw
        }
    }

    Write-Host "[*] Extracting archive..." -ForegroundColor Cyan
    # Expand-Archive comes from a script module, which reads the global preference.
    $progress = $global:ProgressPreference
    $global:ProgressPreference = 'SilentlyContinue'
    try { Expand-Archive -Path $tempZipPath -DestinationPath $tempExtractPath -Force }
    finally { $global:ProgressPreference = $progress }

    # Archives normally contain a single top-level folder ("cds-text-sync-main",
    # "cds-text-sync-v1.7.3"). Some older release assets are flat (files at the
    # archive root) - in that case the extract directory itself is the package.
    $topDirs = @(Get-ChildItem $tempExtractPath -Directory)
    $topFiles = @(Get-ChildItem $tempExtractPath -File)
    if ($topDirs.Count -eq 1 -and $topFiles.Count -eq 0) {
        $extractedPath = $topDirs[0].FullName
    } else {
        $extractedPath = $tempExtractPath
    }

    if (Test-Path -LiteralPath $bodyPath) {
        Write-Host "[*] Updating existing installation..." -ForegroundColor Cyan
        # Backup next to the program folder, never inside ScriptDir.
        $backupPath = "$bodyPath.backup"
        if (-not $dryRun) {
            if (Test-Path -LiteralPath $backupPath) {
                Remove-Item -LiteralPath $backupPath -Recurse -Force
            }
            Copy-Item -LiteralPath $bodyPath -Destination $backupPath -Recurse -Force
        }

        # Carry over user files that live inside the tree and are not shipped in
        # the archive: projects.json at the root (where each project's sync
        # folder is on this machine) and the like. Without this the replace
        # below deletes them silently on every update.
        # Read-only, so a rehearsal computes it too: which of your files would
        # survive is the main thing a rehearsal is asked to report.
        $preserved = @()
        foreach ($rel in @(".")) {
            $preserveSrc = Join-Path $bodyPath $rel
            if (Test-Path -LiteralPath $preserveSrc) {
                foreach ($userFile in Get-ChildItem -LiteralPath $preserveSrc -File -Force) {
                    $shipped = Join-Path (Join-Path $extractedPath $rel) $userFile.Name
                    if (-not (Test-Path -LiteralPath $shipped)) {
                        $preserved += [PSCustomObject]@{
                            Rel  = $rel
                            Name = $userFile.Name
                            Path = $userFile.FullName
                        }
                    }
                }
            }
        }

        $stashDir = Join-Path $env:TEMP ("cts-preserve-" + $PID)
        if ($preserved.Count -gt 0 -and -not $dryRun) {
            New-Item -ItemType Directory -Force -Path $stashDir | Out-Null
            foreach ($item in $preserved) {
                $stashRel = Join-Path $stashDir $item.Rel
                New-Item -ItemType Directory -Force -Path $stashRel | Out-Null
                Copy-Item -LiteralPath $item.Path -Destination (Join-Path $stashRel $item.Name) -Force
            }
        }

        if ($dryRun) {
            Write-Host "[*] Dry run: would back up to $backupPath" -ForegroundColor Magenta
            Write-Host "[*] Dry run: would replace $bodyPath with the downloaded tree" -ForegroundColor Magenta
            Write-Host ("[*] Dry run: would keep " + $preserved.Count + " of your own file(s)") -ForegroundColor Magenta
            foreach ($item in $preserved) {
                Write-Host ("      " + $item.Rel + "\" + $item.Name) -ForegroundColor Magenta
            }
        } else {
            # Replace with new version
            Remove-Item -LiteralPath $bodyPath -Recurse -Force
            Move-Item -LiteralPath $extractedPath -Destination $bodyPath

            foreach ($item in $preserved) {
                $restoreDir = Join-Path $bodyPath $item.Rel
                if (-not (Test-Path -LiteralPath $restoreDir)) {
                    New-Item -ItemType Directory -Force -Path $restoreDir | Out-Null
                }
                Copy-Item -LiteralPath (Join-Path (Join-Path $stashDir $item.Rel) $item.Name) `
                          -Destination (Join-Path $restoreDir $item.Name) -Force
            }
            if ($preserved.Count -gt 0) {
                Write-Host ("[+] Kept " + $preserved.Count + " of your own file(s): " + (($preserved | ForEach-Object { $_.Name }) -join ", ")) -ForegroundColor Green
                Remove-Item -LiteralPath $stashDir -Recurse -Force -ErrorAction SilentlyContinue
            }

            Write-Host "[+] Update completed." -ForegroundColor Green
        }
    } elseif ($dryRun) {
        Write-Host "[*] Dry run: would install cds-text-sync to $bodyPath" -ForegroundColor Magenta
    } else {
        Write-Host "[*] Installing cds-text-sync to $bodyPath..." -ForegroundColor Cyan
        Move-Item -LiteralPath $extractedPath -Destination $bodyPath
        Write-Host "[+] Installation completed!" -ForegroundColor Green
    }
} catch {
    Write-Host "[!] An error occurred: $_" -ForegroundColor Red
    Write-Host "[*] Cleaning up temporary files..." -ForegroundColor Cyan

    # Try to restore from backup if update failed
    if (-not $dryRun -and (Test-Path -LiteralPath "$bodyPath.backup")) {
        if (-not (Test-Path -LiteralPath $bodyPath)) {
            Write-Host "[*] Restoring from backup..." -ForegroundColor Cyan
            Move-Item -LiteralPath "$bodyPath.backup" -Destination $bodyPath
        }
    }
} finally {
    # Cleanup temporary files
    if (Test-Path $tempZipPath) {
        Remove-Item -Path $tempZipPath -Force
    }
    if (Test-Path $tempExtractPath) {
        Remove-Item -Path $tempExtractPath -Recurse -Force
    }
    # A rehearsal makes no backup, so any .backup here belongs to an earlier
    # real install - deleting it would be exactly the kind of damage a rehearsal
    # exists to avoid.
    if (-not $dryRun -and (Test-Path -LiteralPath "$bodyPath.backup")) {
        Remove-Item -LiteralPath "$bodyPath.backup" -Recurse -Force
    }
}

if (Test-Path -LiteralPath $bodyPath) {
    $null = Install-CliCommand -InstallPath $bodyPath

    # The prebuilt agent DLLs and cts.exe live in Git LFS. A GitHub zip carries
    # only their pointer files unless the repository includes LFS objects in
    # archives, so fetch each pointer's content from GitHub's LFS media host.
    $agentDist = Join-Path $bodyPath "products\codesys-agent\dist"
    foreach ($dll in @("Cts.Agent.Core.dll", "Cts.Agent.dll", "cts.exe")) {
        $dllPath = Join-Path $agentDist $dll
        if (-not (Test-Path -LiteralPath $dllPath)) { continue }
        $head = [System.IO.File]::ReadAllBytes($dllPath) | Select-Object -First 24
        if ([System.Text.Encoding]::ASCII.GetString([byte[]]$head) -notlike "version https://git-lfs*") { continue }
        $mediaUrl = "https://media.githubusercontent.com/media/ArthurkaX/cds-text-sync/$mediaRef/products/codesys-agent/dist/$dll"
        if ($dryRun) {
            Write-Host "[*] Dry run: would download $dll from $mediaUrl" -ForegroundColor Magenta
            continue
        }
        Write-Host "[*] Downloading the in-IDE agent: $dll" -ForegroundColor Cyan
        try {
            Save-Url $mediaUrl $dllPath
        } catch {
            Write-Host "[!] Could not download $dll ($_). The menu works; the agent needs it - re-run the installer." -ForegroundColor Yellow
        }
    }

    # The menu entry, the agent and its toolbar button: cts.exe from the
    # download installs them. Its --check rehearses the install for real --
    # ScriptDir discovery, an older install in the way, the toolbar files --
    # and writes nothing.
    Write-Host "`n--- CODESYS Menu ---" -ForegroundColor Cyan
    $ctsExe = Join-Path $agentDist "cts.exe"
    # Astra.IDE keeps its own ScriptDir next to CODESYS's: the standard
    # path serves both IDEs when Astra.IDE is installed.
    $menuTargets = @($targetBaseDir)
    $astraScriptDir = Join-Path $env:LOCALAPPDATA "Astra.IDE\ScriptDir"
    if ($targetBaseDir -eq $localAppDataScriptDir -and (Test-Path -LiteralPath $astraScriptDir)) {
        $menuTargets += $astraScriptDir
    }
    # CODESYS before 3.5.17 reads only the machine-wide ScriptDir; a newer one
    # beside it shows the entry once, not twice, so both get it.
    if ($targetBaseDir -eq $localAppDataScriptDir -and $recommendation.LegacyDetected -and $recommendation.ModernDetected) {
        $legacyWritable = $dryRun
        if (-not $dryRun) {
            try {
                New-Item -ItemType Directory -Force -Path $programDataScriptDir -ErrorAction Stop | Out-Null
                $probeFile = Join-Path $programDataScriptDir (".cts_write_test_" + $PID)
                Set-Content -Path $probeFile -Value "test" -ErrorAction Stop
                Remove-Item -Path $probeFile -Force -ErrorAction SilentlyContinue
                $legacyWritable = $true
            } catch {
                $legacyWritable = $false
            }
        }
        if ($legacyWritable) {
            $menuTargets += $programDataScriptDir
        } else {
            Write-Host "[!] The legacy CODESYS reads only $programDataScriptDir, which needs administrator rights." -ForegroundColor Yellow
            Write-Host "    From an elevated PowerShell, once:" -ForegroundColor Yellow
            Write-Host "    & `"$ctsExe`" install --script-dir `"$programDataScriptDir`" --toolbar" -ForegroundColor Cyan
        }
    }
    $ctsHead = if (Test-Path -LiteralPath $ctsExe) { [System.IO.File]::ReadAllBytes($ctsExe) | Select-Object -First 2 } else { @() }
    if (-not ($ctsHead.Count -eq 2 -and $ctsHead[0] -eq 0x4D -and $ctsHead[1] -eq 0x5A)) {
        Write-Host "[!] $ctsExe is not the program (a Git LFS pointer the download did not replace); the menu is not installed. Re-run the installer." -ForegroundColor Yellow
        $menuTargets = @()
    }
    foreach ($menuTarget in $menuTargets) {
        $menuArgs = @("install", "--script-dir", "$menuTarget", "--toolbar")
        if ($dryRun) {
            $menuArgs += "--check"
        }
        & $ctsExe @menuArgs
        if ($LASTEXITCODE -ne 0 -and -not $dryRun) {
            Write-Host "[!] The menu was not installed completely. Run it again once CODESYS is closed:" -ForegroundColor Yellow
            Write-Host "    & `"$ctsExe`" install --script-dir `"$menuTarget`" --toolbar" -ForegroundColor Yellow
        }
    }
}

Write-Host "`n--- Setup Finished! ---" -ForegroundColor Cyan
Write-Host ("  Program : " + $bodyPath)
Write-Host ("  Menu    : " + $menuDir)
Write-Host ("  CLI     : " + (Join-Path $bodyPath "products\codesys-agent\dist\cts.exe"))
if ($dryRun) {
    Write-Host "`n  DRY RUN: none of the above was actually written." -ForegroundColor Magenta
} else {
    Write-Host "`n  If added, new terminals pick up the updated user PATH. Check anytime with:  cts install --check" -ForegroundColor DarkGray
    Write-Host "`n--- Next, in CODESYS ---" -ForegroundColor Cyan
    Write-Host "  1. Use the cds-text-sync toolbar button (blue arrows around CTS) to start the agent and open the quick window."
    Write-Host "     It does the same as Tools > Scripting > Scripts > C > cds-text-sync."
    Write-Host "     If CODESYS was open during setup, close it and run: cts install --toolbar"
    Write-Host "  2. Press Alt+Q, then 8 and 1: Enter takes the suggested sync folder."
    Write-Host "  3. Alt+Q again: on a new folder, 2 (IDE -> Disk) writes the project to disk."
}
