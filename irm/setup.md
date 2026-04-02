# Setup Script for cds-text-sync

This directory contains a PowerShell setup script designed to automate the installation and update process for the `cds-text-sync` tool.

## How to execute

You can run the script directly from GitHub using a single command in PowerShell (run as Administrator if you need to install Git):

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

## What the script does

1.  **Environment Check**:
    - Verifies if **Git** is installed on your system.
    - If Git is missing, it offers to install it automatically using `winget`.
2.  **Version Selection**:
    - Fetches available stable releases from GitHub (tags starting with `vX.Y.Z`).
    - Displays an interactive menu with the **last 5 stable versions**.
    - **Default option (L)**: Latest development version from `main` branch.
    - Shows the **recommended stable** version marked with `(recommended stable)`.
    - Allows you to select any version from the list.
3.  **Directory Management**:
    - Ensures the required directory structure exists: `%LOCALAPPDATA%\CODESYS\ScriptDir\`.
4.  **Deployment**:
    - **First time install**: If the project is not present, it performs a `git clone --depth 1` with the selected version branch.
    - **Update**: If the project is already installed, it navigates into the folder and performs a `git fetch --depth 1` and `git reset --hard` to the selected version, overwriting local modifications.

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
- **Internet Connection**: Required to download Git and the repository.
