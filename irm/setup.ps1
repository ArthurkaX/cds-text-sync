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
        
        # Refresh PATH environment variable for the current session
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

# 2. Create required directories if they don't exist
if (-not (Test-Path $targetBaseDir)) {
    Write-Host "[*] Creating directory: $targetBaseDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $targetBaseDir | Out-Null
}

# 3. Clone repository or update if it already exists
if (Test-Path $fullPath) {
    Write-Host "[*] Project folder already exists. Attempting to update..." -ForegroundColor Cyan
    # Navigate to the folder and pull latest changes
    Push-Location $fullPath
    git pull
    Pop-Location
    Write-Host "[+] Update completed." -ForegroundColor Green
} else {
    Write-Host "[*] Cloning repository to $fullPath..." -ForegroundColor Cyan
    git clone $repoUrl $fullPath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[+] Project successfully cloned!" -ForegroundColor Green
    } else {
        Write-Host "[!] An error occurred during cloning." -ForegroundColor Red
    }
}

Write-Host "`n--- Setup Finished! ---" -ForegroundColor Cyan
