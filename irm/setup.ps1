# Set encoding to UTF8 for correct character display
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoUrl = "https://github.com/ArthurkaX/cds-text-sync"
$targetBaseDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
$repoName = "cds-text-sync"
$fullPath = Join-Path $targetBaseDir $repoName

Write-Host "--- Environment Setup: cds-text-sync ---" -ForegroundColor Cyan

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

Write-Host "`n--- Setup Finished! ---" -ForegroundColor Cyan
