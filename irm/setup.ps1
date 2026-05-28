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
            if ($tag -match "^v\d+\.\d+\.\d+$") {
                $stableTags += $tag
            } elseif ($tag -match "^v\d+\.\d+\.\d+-test\.\d+$" -or [bool]$release.prerelease) {
                $testTags += $tag
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
Write-Host "[L] Latest (main branch) [DEFAULT]" -ForegroundColor Green

if ($stableTags.Count -gt 0) {
    Write-Host "Stable Releases (last $($stableTags.Count)):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $stableTags.Count; $i++) {
        $tag = $stableTags[$i]
        $isLatest = ($i -eq ($stableTags.Count - 1))
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
$versionName = ""

if ($choice -eq "L") {
    $zipUrl = "$repoUrl/archive/refs/heads/main.zip"
    $versionName = "main"
} elseif ($choice -match '^[Tt](\d+)$') {
    $testIndex = [int]$matches[1] - 1
    if ($testIndex -ge 0 -and $testIndex -lt $testTags.Count) {
        $selectedTag = $testTags[$testIndex]
        $zipUrl = "$repoUrl/archive/refs/tags/$selectedTag.zip"
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
        $zipUrl = "$repoUrl/archive/refs/tags/$selectedTag.zip"
        $versionName = $selectedTag
    } else {
        Write-Host "[!] Invalid selection. Falling back to main branch." -ForegroundColor Yellow
        $zipUrl = "$repoUrl/archive/refs/heads/main.zip"
        $versionName = "main"
    }
}

# 5. Installation Path Selection
Write-Host "`n--- Installation Path ---" -ForegroundColor Cyan
Write-Host "[1] Standard CODESYS (%LOCALAPPDATA%\CODESYS\ScriptDir\) [DEFAULT]"
Write-Host "[2] Alternative path (for KeStudio, DIA Designer-AX, etc.)"

$pathChoice = Read-Host "`nSelect installation path [1, 2] (default: 1)"
if ([string]::IsNullOrWhiteSpace($pathChoice)) {
    $pathChoice = "1"
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
            New-Item -ItemType Directory -Force -Path $targetBaseDir | Out-Null
            Write-Host "[+] Directory created successfully." -ForegroundColor Green
        } catch {
            Write-Host "[!] Failed to create directory: $_" -ForegroundColor Red
            Write-Host "[*] Falling back to standard path..." -ForegroundColor Yellow
            $targetBaseDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
        }
    }

    # Update fullPath with new targetBaseDir
    $fullPath = Join-Path $targetBaseDir $repoName
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
    Invoke-WebRequest -Uri $zipUrl -OutFile $tempZipPath -UseBasicParsing
    
    Write-Host "[*] Extracting archive..." -ForegroundColor Cyan
    Expand-Archive -Path $tempZipPath -DestinationPath $tempExtractPath -Force
    
    # Find the extracted folder (it will be named "cds-text-sync-main" or "cds-text-sync-v1.7.3")
    $extractedFolder = Get-ChildItem $tempExtractPath -Directory | Select-Object -First 1
    $extractedPath = $extractedFolder.FullName
    
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
