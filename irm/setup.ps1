# Set encoding to UTF8 for correct character display
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoUrl = "https://github.com/ArthurkaX/cds-text-sync.git"
$targetBaseDir = Join-Path $env:LOCALAPPDATA "CODESYS\ScriptDir"
$repoName = "cds-text-sync"
$fullPath = Join-Path $targetBaseDir $repoName

Write-Host "--- Environment Setup: cds-text-sync ---" -ForegroundColor Cyan

# 1. Check for Git installation
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[-] Git not found." -ForegroundColor Yellow
    $choice = Read-Host "Would you like to install Git via winget? (Y/N)"
    if ($choice -eq 'Y' -or $choice -eq 'y') {
        Write-Host "[*] Installing Git... Please wait." -ForegroundColor Cyan
        winget install --id Git.Git -e --source winget
        
        # Refresh PATH environment variable for current session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Host "[!] Git installed but terminal restart may be required. Please restart your console and run the script again." -ForegroundColor Red
            return
        }
    } else {
        Write-Host "[!] Git is required for this script to function. Aborting." -ForegroundColor Red
        return
    }
} else {
    Write-Host "[+] Git is already installed." -ForegroundColor Green
}

# 2. Get available stable releases
Write-Host "`n[*] Fetching available versions..." -ForegroundColor Cyan
$tags = @()
try {
    $remoteTags = $(git ls-remote --tags $repoUrl 2>&1)
    if ($LASTEXITCODE -eq 0) {
        # Parse tags and filter only version tags (vX.Y.Z)
        $tags = $remoteTags | 
            Select-String "refs/tags/v" | 
            ForEach-Object { $_.ToString().Split('/')[-1] } |
            Where-Object { $_ -match "^v\d+\.\d+\.\d+$" }
        
        # Get last 5 stable versions
        if ($tags.Count -gt 5) {
            $tags = $tags | Select-Object -Last 5
        }
    }
} catch {
    Write-Host "[!] Warning: Could not fetch tags. Only main branch will be available." -ForegroundColor Yellow
}

# 3. Show version selection menu
Write-Host "`n--- Version Selection ---" -ForegroundColor Cyan
Write-Host "[L] Latest (main branch) [DEFAULT]" -ForegroundColor Green

if ($tags.Count -gt 0) {
    Write-Host "Stable Releases (last $($tags.Count)):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $tags.Count; $i++) {
        $tag = $tags[$i]
        $isLatest = ($i -eq ($tags.Count - 1))
        $label = if ($isLatest) { " (recommended stable)" } else { "" }
        Write-Host "[$($i+1)] $tag$label" -ForegroundColor Yellow
    }
}

$choice = Read-Host "`nSelect version [L, 1-$($tags.Count)] (default: L)"
if ([string]::IsNullOrWhiteSpace($choice)) {
    $choice = "L"
}

# 4. Create required directories if they don't exist
if (-not (Test-Path $targetBaseDir)) {
    Write-Host "[*] Creating directory: $targetBaseDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $targetBaseDir | Out-Null
}

# 5. Clone or update repository
if (Test-Path $fullPath) {
    Write-Host "[*] Project folder already exists. Attempting to update..." -ForegroundColor Cyan
    # Navigate to the folder and fetch latest changes
    Push-Location $fullPath
    
    if ($choice -eq "L") {
        # Update to latest main branch
        git fetch --depth 1 origin main
        if ($LASTEXITCODE -eq 0) {
            git reset --hard origin/main
        }
    } else {
        # Update to selected tag
        $tagIndex = [int]$choice - 1
        if ($tagIndex -ge 0 -and $tagIndex -lt $tags.Count) {
            $selectedTag = $tags[$tagIndex]
            git fetch --depth 1 origin $selectedTag
            if ($LASTEXITCODE -eq 0) {
                git reset --hard $selectedTag
            }
        } else {
            Write-Host "[!] Invalid selection. Falling back to main branch." -ForegroundColor Yellow
            git fetch --depth 1 origin main
            if ($LASTEXITCODE -eq 0) {
                git reset --hard origin/main
            }
        }
    }
    
    Pop-Location
    Write-Host "[+] Update completed." -ForegroundColor Green
} else {
    # Clone repository
    if ($choice -eq "L") {
        Write-Host "[*] Cloning latest version from main branch to $fullPath..." -ForegroundColor Cyan
        git clone --depth 1 --branch main $repoUrl $fullPath
    } else {
        $tagIndex = [int]$choice - 1
        if ($tagIndex -ge 0 -and $tagIndex -lt $tags.Count) {
            $selectedTag = $tags[$tagIndex]
            Write-Host "[*] Cloning stable version $selectedTag to $fullPath..." -ForegroundColor Cyan
            git clone --depth 1 --branch $selectedTag $repoUrl $fullPath
        } else {
            Write-Host "[!] Invalid selection. Cloning latest version from main branch..." -ForegroundColor Yellow
            git clone --depth 1 --branch main $repoUrl $fullPath
        }
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[+] Project successfully cloned!" -ForegroundColor Green
    } else {
        Write-Host "[!] An error occurred during cloning." -ForegroundColor Red
    }
}

Write-Host "`n--- Setup Finished! ---" -ForegroundColor Cyan
