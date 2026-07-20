# Set encoding to UTF8 for correct character display
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoUrl = "https://github.com/ArthurkaX/cds-text-sync"
$targetBaseDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
$repoName = "cds-text-sync"
$fullPath = Join-Path $targetBaseDir $repoName

Write-Host "--- Environment Setup: cds-text-sync ---" -ForegroundColor Cyan

function Test-PythonCommandName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    try {
        $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
        if (-not $cmd) {
            return $false
        }

        $versionOutput = & $CommandName --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        $versionText = [string]($versionOutput -join " ")
        if ($versionText -notmatch "Python\s+3\.") {
            return $false
        }

        return $true
    } catch {
        return $false
    }
}

function Test-PythonCommand {
    return ((Test-PythonCommandName -CommandName "python") -or (Test-PythonCommandName -CommandName "python.exe"))
}

function Get-PythonCommandName {
    if (Test-PythonCommandName -CommandName "python") {
        return "python"
    }
    if (Test-PythonCommandName -CommandName "python.exe") {
        return "python.exe"
    }
    return $null
}

function Show-PythonConfigurationHelp {
    Write-Host "`nPython was found only partially, or it is not reachable as a working Python 3 command." -ForegroundColor Yellow
    Write-Host "cds-text-sync expects this command to work from a new PowerShell/CMD window:" -ForegroundColor Yellow
    Write-Host "    python --version" -ForegroundColor Cyan
    Write-Host "`nRecommended fixes:" -ForegroundColor Cyan
    Write-Host "  1. Re-run the Python installer and enable 'Add python.exe to PATH'."
    Write-Host "  2. Restart PowerShell/CMD after installation."
    Write-Host "  3. Disable broken Windows App Execution Aliases for python.exe if they shadow a real install."
    Write-Host "     Settings -> Apps -> Advanced app settings -> App execution aliases."
    Write-Host "  4. Verify manually: python --version"
}

function Offer-PythonInstall {
    Write-Host "`n[!] A working Python 3 command was not found." -ForegroundColor Yellow
    Write-Host '    cds-text-sync needs `python --version` to work from PowerShell/CMD.' -ForegroundColor Yellow
    Write-Host "`nChoose an option:" -ForegroundColor Cyan
    Write-Host "[W] Install with winget" -ForegroundColor Green
    Write-Host "[M] Open manual download page" -ForegroundColor Green
    Write-Host "[C] Show PATH / App Execution Alias configuration help" -ForegroundColor Green
    Write-Host "[S] Skip for now and continue anyway" -ForegroundColor Green

    $pythonChoice = Read-Host "`nSelect option [W, M, C, S] (default: W)"
    if ([string]::IsNullOrWhiteSpace($pythonChoice)) {
        $pythonChoice = "W"
    }

    switch ($pythonChoice.ToUpperInvariant()) {
        "W" {
            $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
            if (-not $wingetCmd) {
                Write-Host "[!] winget was not found on this machine." -ForegroundColor Yellow
                Write-Host "[*] Opening the manual download page instead..." -ForegroundColor Cyan
                Start-Process "https://www.python.org/downloads/windows/"
                return $false
            }

            Write-Host "[*] Installing Python with winget..." -ForegroundColor Cyan
            $wingetArgs = @(
                "install",
                "-e",
                "--id",
                "Python.Python.3.13",
                "--accept-package-agreements",
                "--accept-source-agreements"
            )
            $proc = Start-Process -FilePath "winget" -ArgumentList $wingetArgs -Wait -PassThru
            if ($proc.ExitCode -ne 0) {
                Write-Host "[!] winget install failed with exit code $($proc.ExitCode)." -ForegroundColor Red
                Write-Host "[*] You can install Python manually from: https://www.python.org/downloads/windows/" -ForegroundColor Yellow
                return $false
            }

            if (Test-PythonCommand) {
                Write-Host "[+] Python is now available." -ForegroundColor Green
                return $true
            }

            Write-Host '[!] winget finished, but `python --version` is still not working in this shell.' -ForegroundColor Yellow
            Show-PythonConfigurationHelp
            return $false
        }
        "M" {
            Write-Host "[*] Opening the Python download page..." -ForegroundColor Cyan
            Start-Process "https://www.python.org/downloads/windows/"
            Show-PythonConfigurationHelp
            return $false
        }
        "C" {
            Show-PythonConfigurationHelp
            return $false
        }
        default {
            Write-Host "[*] Skipping Python installation step." -ForegroundColor Yellow
            Show-PythonConfigurationHelp
            return $false
        }
    }
}

function Install-CliCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallPath
    )

    $pythonName = Get-PythonCommandName
    if (-not $pythonName) {
        Write-Host "[!] Python is not available; skipping CLI command installation." -ForegroundColor Yellow
        Write-Host "    After installing Python, run:" -ForegroundColor Yellow
        Write-Host "    python -m pip install -e `"$InstallPath`"" -ForegroundColor Yellow
        return $false
    }

    Write-Host "`n--- CLI Installation ---" -ForegroundColor Cyan
    Write-Host "Install the system CLI command `cds-text-sync` with pip editable mode?"
    Write-Host "This lets agents and humans run: cds-text-sync --help" -ForegroundColor Green
    $cliChoice = Read-Host "`nInstall CLI command [Y, N] (default: Y)"
    if ([string]::IsNullOrWhiteSpace($cliChoice)) {
        $cliChoice = "Y"
    }
    if ($cliChoice.ToUpperInvariant() -ne "Y") {
        Write-Host "[*] Skipping CLI installation." -ForegroundColor Yellow
        Write-Host "    You can install later with:" -ForegroundColor Yellow
        Write-Host "    $pythonName -m pip install -e `"$InstallPath`"" -ForegroundColor Yellow
        return $false
    }

    try {
        Write-Host "[*] Installing CLI command from: $InstallPath" -ForegroundColor Cyan
        $pipArgs = @("-m", "pip", "install", "-e", $InstallPath)
        $proc = Start-Process -FilePath $pythonName -ArgumentList $pipArgs -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -ne 0) {
            Write-Host "[!] CLI installation failed with exit code $($proc.ExitCode)." -ForegroundColor Red
            Write-Host "    Try manually: $pythonName -m pip install -e `"$InstallPath`"" -ForegroundColor Yellow
            return $false
        }

        $cliCmd = Get-Command cds-text-sync -ErrorAction SilentlyContinue
        if ($cliCmd) {
            Write-Host "[+] CLI installed: cds-text-sync" -ForegroundColor Green
            return $true
        }

        Write-Host "[!] pip completed, but cds-text-sync is not visible in this shell." -ForegroundColor Yellow
        Write-Host "    Restart PowerShell/CMD or make sure Python Scripts is in PATH." -ForegroundColor Yellow
        return $true
    } catch {
        Write-Host "[!] CLI installation error: $_" -ForegroundColor Red
        Write-Host "    Try manually: $pythonName -m pip install -e `"$InstallPath`"" -ForegroundColor Yellow
        return $false
    }
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
        $reason = "Both legacy and modern CODESYS detected - defaulting to the user path. If scripts do not appear on the legacy install, re-run and pick the Legacy path (3)."
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

if (-not (Test-PythonCommand)) {
    $pythonReady = Offer-PythonInstall
    if (-not $pythonReady -and -not (Test-PythonCommand)) {
        Write-Host '[!] Python is still unavailable. The installer can continue, but the package will not run until `python` is installed.' -ForegroundColor Yellow
    }
}

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
Write-Host "[L] Latest development snapshot (main branch) [DEFAULT]" -ForegroundColor Green

if ($stableTags.Count -gt 0) {
    Write-Host "Stable Releases (last $($stableTags.Count)):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $stableTags.Count; $i++) {
        $tag = $stableTags[$i]
        $isLatest = ($i -eq 0)
        $label = if ($isLatest) { " (recommended stable)" } else { "" }
        Write-Host "[$($i+1)] $tag$label" -ForegroundColor Yellow
    }
}

if ($testTags.Count -gt 0) {
    Write-Host "Test / Pre-release Builds (last $($testTags.Count)):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $testTags.Count; $i++) {
        $tag = $testTags[$i]
        $isLatest = ($i -eq 0)
        $label = if ($isLatest) { " (latest test build)" } else { "" }
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
$zipUrl = ""
$fallbackZipUrl = ""
$versionName = ""

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
    Write-Host "`nFor more details, see: https://github.com/ArthurkaX/cds-text-sync/blob/main/ALTERNATIVE_INSTALLATIONS.md" -ForegroundColor Yellow

    $targetBaseDir = Read-Host "`nEnter the full path to ScriptDir"

    # Remove quotes from path if present
    $targetBaseDir = $targetBaseDir.Trim('"', "'")

    # Validate path - create parent directories if needed
    if (-not (Test-Path $targetBaseDir)) {
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
} elseif ($pathChoice -eq "3") {
    $targetBaseDir = $programDataScriptDir
    $targetIsProgramData = $true
    Write-Host "[*] Using legacy machine-wide path: $targetBaseDir" -ForegroundColor Cyan
} else {
    $targetBaseDir = $localAppDataScriptDir
}

# Update fullPath with the resolved targetBaseDir
$fullPath = Join-Path $targetBaseDir $repoName

# 5b. If installing into ProgramData, verify write access up front.
# %PROGRAMDATA%\CODESYS usually needs administrator rights. On failure we warn,
# print the exact elevated copy command, and fall back to the user path so the
# package and CLI still install (the legacy CODESYS only sees the scripts once
# they are copied into ProgramData).
if ($targetIsProgramData) {
    $canWriteProgramData = $false
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

    if (-not $canWriteProgramData) {
        Write-Host "`n[!] No write permission for the legacy ProgramData ScriptDir:" -ForegroundColor Yellow
        Write-Host "    $targetBaseDir" -ForegroundColor Yellow
        Write-Host "    This path typically requires administrator rights." -ForegroundColor Yellow
        Write-Host "`n    Fix option A - re-run this installer from an elevated PowerShell (Run as administrator)." -ForegroundColor Cyan
        Write-Host "    Fix option B - after this run, copy the files once from an elevated PowerShell:" -ForegroundColor Cyan
        Write-Host "        Copy-Item -Recurse -Force `"$localAppDataScriptDir\$repoName`" `"$targetBaseDir\`"" -ForegroundColor Cyan
        Write-Host "`n[*] Falling back to the standard user path so the package and CLI still install:" -ForegroundColor Yellow
        Write-Host "    $localAppDataScriptDir" -ForegroundColor Yellow
        Write-Host "    (On legacy CODESYS the scripts appear only after they exist in ProgramData.)" -ForegroundColor Yellow
        $targetBaseDir = $localAppDataScriptDir
        $targetIsProgramData = $false
        $fullPath = Join-Path $targetBaseDir $repoName
    }
}

# 6. Create required directories if they don't exist
if (-not (Test-Path $targetBaseDir)) {
    Write-Host "[*] Creating directory: $targetBaseDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $targetBaseDir | Out-Null
}

# 6. Download and install
$tempZipPath = "$env:TEMP\cds-text-sync-$versionName.zip"
$tempExtractPath = "$env:TEMP\cds-text-sync-temp-$versionName"

try {
    Write-Host "[*] Downloading cds-text-sync ($versionName)..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tempZipPath -UseBasicParsing
    } catch {
        if ($fallbackZipUrl) {
            Write-Host "[!] Release asset not available; downloading source archive for $versionName instead." -ForegroundColor Yellow
            Invoke-WebRequest -Uri $fallbackZipUrl -OutFile $tempZipPath -UseBasicParsing
        } else {
            throw
        }
    }

    Write-Host "[*] Extracting archive..." -ForegroundColor Cyan
    Expand-Archive -Path $tempZipPath -DestinationPath $tempExtractPath -Force

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
    
    if (Test-Path $fullPath) {
        Write-Host "[*] Updating existing installation..." -ForegroundColor Cyan
        # Backup existing installation
        $backupPath = "$fullPath.backup"
        if (Test-Path $backupPath) {
            Remove-Item -Path $backupPath -Recurse -Force
        }
        Copy-Item -Path $fullPath -Destination $backupPath -Recurse -Force
        
        # Replace with new version
        Remove-Item -Path $fullPath -Recurse -Force
        Move-Item -Path $extractedPath -Destination $fullPath
        
        Write-Host "[+] Update completed." -ForegroundColor Green
    } else {
        Write-Host "[*] Installing cds-text-sync to $fullPath..." -ForegroundColor Cyan
        Move-Item -Path $extractedPath -Destination $fullPath
        Write-Host "[+] Installation completed!" -ForegroundColor Green
    }
} catch {
    Write-Host "[!] An error occurred: $_" -ForegroundColor Red
    Write-Host "[*] Cleaning up temporary files..." -ForegroundColor Cyan
    
    # Try to restore from backup if update failed
    if (Test-Path "$fullPath.backup") {
        if (-not (Test-Path $fullPath)) {
            Write-Host "[*] Restoring from backup..." -ForegroundColor Cyan
            Move-Item -Path "$fullPath.backup" -Destination $fullPath
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
    if (Test-Path "$fullPath.backup") {
        Remove-Item -Path "$fullPath.backup" -Recurse -Force
    }
}

if (Test-Path $fullPath) {
    Install-CliCommand -InstallPath $fullPath | Out-Null
}

Write-Host "`n--- Setup Finished! ---" -ForegroundColor Cyan
