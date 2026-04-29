# Setup Script for cds-text-sync

Automate the installation and update of `cds-text-sync` with a single command.

## Quick Start

Run in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!NOTE]
> **No Git required.** The script downloads clean zip archives directly from GitHub.

## Features

- **Path Selection**: Choose between standard CODESYS paths or custom paths for forks (KeStudio, DIA Designer, etc.).
- **Version Control**: Interactive menu with the latest `main` branch, the last 5 stable releases, and the last 5 test / pre-release builds.
- **Auto-Update**: Detects existing versions, creates backups, and replaces files safely.
- **Clean Install**: No `.git` history, minimal disk footprint (~5MB).

## Requirements

- **OS**: Windows 10/11
- **PowerShell**: 5.1 or higher
- **Internet**: Required for download
- **Python 3**: The installer checks for the `python` command and can offer either a manual download page or a `winget` install if Python is missing

## Alternative Installations (Forks)

If you use KeStudio, DIA Designer-AX, or another fork:

1. Select **Option 2** in the installer.
2. Provide your `ScriptDir` path (Shift + Right-click folder -> **Copy as path**).
3. See [ALTERNATIVE_INSTALLATIONS.md](../ALTERNATIVE_INSTALLATIONS.md) for details.
