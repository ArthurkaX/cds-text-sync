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
2.  **Directory Management**:
    - Ensures the required directory structure exists: `%LOCALAPPDATA%\CODESYS\ScriptDir\`.
3.  **Deployment**:
    - **First time install**: If the project is not present, it performs a `git clone` to download the tool.
    - **Update**: If the project is already installed, it navigates into the folder and performs a `git pull` to fetch the latest updates from the repository.

## Requirements

- **Operating System**: Windows (10/11)
- **PowerShell**: Version 5.1 or higher
- **Internet Connection**: Required to download Git and the repository.
