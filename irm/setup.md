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

- **Version-Aware Path**: Detects the installed CODESYS version and recommends the right `ScriptDir`. Newer CODESYS uses `%LOCALAPPDATA%\CODESYS\ScriptDir`; older CODESYS (before ~V3.5 SP17, e.g. 3.5.16) only scans `%PROGRAMDATA%\CODESYS\ScriptDir` — pick **[3] Legacy CODESYS** for those (may require administrator rights).
- **Path Selection**: Choose between the standard user path, the legacy machine-wide path, or a custom path for forks (KeStudio, DIA Designer, etc.).
- **Two Folders**: The tool is installed to a program folder (default `%LOCALAPPDATA%\cds-text-sync`) and only the generated `Project_*.py` menu scripts go into `ScriptDir`. CODESYS scans `ScriptDir` recursively, so keeping the program out of it is what keeps the scripting menu down to the commands you use.
- **Migration**: An older installation sitting inside `ScriptDir` is moved out rather than copied, so untracked files of yours under `profiles/` come along.
- **Version Control**: Interactive menu with the latest `main` branch, the last 5 stable releases, and the last 5 test / pre-release builds.
- **Auto-Update**: Detects existing versions, creates backups, and replaces files safely.
- **CLI Install**: Offers to run `python -m pip install -e <program-folder>` so `cds-text-sync` is available from any shell.
- **Clean Install**: No `.git` history, minimal disk footprint (~5MB).

## Requirements

- **OS**: Windows 10/11
- **PowerShell**: 5.1 or higher
- **Internet**: Required for download
- **Python 3.11+**: The installer checks that `python --version` works and reports Python 3.11 or newer. If Python is missing, too old, or not reachable from PowerShell/CMD, it can offer `winget` installation, open the manual download page, or show PATH / Windows App Execution Alias configuration hints. Python is required for the system CLI command.

## CLI Command

After the tool is installed into the program folder, the installer asks whether to install the system CLI command. This is a separate required step for CLI usage; the generated menu scripts only make the CODESYS commands available.

```powershell
python -m pip install -e "<program-folder>"
```

Choose **Y** to make this work from any shell:

```powershell
cts --help
cts ping --timeout 10
cts where          # program folder, ScriptDir, and menu status
```

## Alternative Installations (Forks)

If you use KeStudio, DIA Designer-AX, or another fork:

1. Select **Option 2** in the installer.
2. Provide your `ScriptDir` path (Shift + Right-click folder -> **Copy as path**).
3. See [Alternative Installations](../docs/alternative-installations.md) for details.
