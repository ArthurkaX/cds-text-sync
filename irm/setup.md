# Setup Script for cds-text-sync

This directory contains a PowerShell setup script designed to automate the installation and update process for the `cds-text-sync` tool.

## How to execute

You can run the script directly from GitHub using a single command in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

**No Git installation required** - the script downloads clean zip archives from GitHub.

## What the script does

1.  **Installation Path Selection**:
    - **Option 1**: Standard CODESYS user profile path (`%LOCALAPPDATA%\CODESYS\ScriptDir\`)
    - **Option 2**: Alternative path for forks (KeStudio, DIA Designer-AX, etc.)
    - Automatically creates directory if it doesn't exist
2.  **Version Selection**:
    - Fetches available stable releases from GitHub (tags starting with `vX.Y.Z`).
    - Displays an interactive menu with the **last 5 stable versions**.
    - **Default option (L)**: Latest development version from `main` branch.
    - Shows the **recommended stable** version marked with `(recommended stable)`.
    - Allows you to select any version from the list.
3.  **Installation**:
    - Downloads the selected version as a clean zip archive from GitHub.
    - **Stable releases**: Downloads from `archive/refs/tags/vX.Y.Z.zip` - no `.git` folder, smaller size.
    - **Latest version**: Downloads from `archive/refs/heads/main.zip` - also clean archive without `.git`.
    - Extracts to the selected ScriptDir directory.
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

## Alternative Installations

If you're using a CODESYS fork or alternative installation (KeStudio, DIA Designer-AX, etc.):

1. Select **Option 2** in the installation path menu
2. Copy your ScriptDir folder path:
   - Navigate to your installation folder in File Explorer
   - Right-click on the `ScriptDir` folder
   - Hold **Shift** and select **"Copy as path"**
   - Paste into the setup script
3. For more details and supported environments, see [ALTERNATIVE_INSTALLATIONS.md](../ALTERNATIVE_INSTALLATIONS.md)

> [!NOTE]
> The setup script will automatically create the ScriptDir directory if it doesn't exist.
