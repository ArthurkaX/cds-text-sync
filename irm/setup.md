# Setup Script for cds-text-sync

This directory contains a PowerShell setup script designed to automate the installation and update process for the `cds-text-sync` tool.

## How to execute

You can run the script directly from GitHub using a single command in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

**No Git installation required** - the script downloads clean zip archives from GitHub.

## What the script does

1.  **Version Selection**:
    - Fetches available stable releases from GitHub (tags starting with `vX.Y.Z`).
    - Displays an interactive menu with the **last 5 stable versions**.
    - **Default option (L)**: Latest development version from `main` branch.
    - Shows the **recommended stable** version marked with `(recommended stable)`.
    - Allows you to select any version from the list.
2.  **Directory Management**:
    - Ensures the required directory structure exists: `%LOCALAPPDATA%\CODESYS\ScriptDir\`.
3.  **Installation**:
    - Downloads the selected version as a clean zip archive from GitHub.
    - **Stable releases**: Downloads from `archive/refs/tags/vX.Y.Z.zip` - no `.git` folder, smaller size.
    - **Latest version**: Downloads from `archive/refs/heads/main.zip` - also clean archive without `.git`.
    - Extracts to `%LOCALAPPDATA%\CODESYS\ScriptDir\cds-text-sync`.
4.  **Update**:
    - If an existing installation is found, it creates a backup.
    - Downloads and extracts the new version.
    - Replaces the old installation.
    - Automatically cleans up temporary files and backup.

## Version Selection Menu Example

The script presents the following menu:

```
--- Version Selection ---
[L] Latest (main branch) [DEFAULT]
Stable Releases (last 5):
[1] v1.7.1
[2] v1.7.2
[3] v1.7.3 (recommended stable)

Select version [L, 1-3] (default: L)
```

- Press `Enter` or type `L` for the latest development version.
- Type a number (1, 2, 3...) to select a specific stable release.
- The most recent stable version is always marked as **recommended stable**.

## Requirements

- **Operating System**: Windows (10/11)
- **PowerShell**: Version 5.1 or higher
- **Internet Connection**: Required to download the script and the selected version.

## Advantages

- **No Git required**: The script uses `Invoke-WebRequest` to download zip archives directly from GitHub.
- **Clean installation**: No `.git` folder, no repository history, smaller disk footprint (~5MB vs ~10MB+ with full history).
- **Safe updates**: Automatic backup before updating, with rollback capability if something fails.
- **Fast downloads**: Downloads only the files you need, not the entire repository history.
