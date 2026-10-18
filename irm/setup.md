# Setup Script for cds-text-sync

Automate the installation and update of `cds-text-sync` with a single command.

## Quick Start

Run in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!NOTE]
> **No Git needed for the download.** The script downloads clean zip archives
> directly from GitHub. Each project's sync folder is a git repository, so the
> installer checks for Git too (see Requirements).

### A test branch

A line shared for testing before a release is installed by name, without the version menu: set `CTS_BRANCH` and take the script from that branch.

```powershell
$env:CTS_BRANCH = "<branch>"; irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/<branch>/irm/setup.ps1 | iex
```

Run it again the same way to update; clear the variable (`Remove-Item Env:CTS_BRANCH`) for the menu.

### From an archive

A build handed over as a file (a PC without GitHub access, a line not published there) comes as a `*-setup.zip`: unzip it and run `install.cmd`. It runs this installer on the archive beside it, the same steps as above without downloading. By hand:

```powershell
$env:CTS_ARCHIVE = "C:\path\to\cds-text-sync-<line>-<commit>.zip"; .\setup.ps1
```

`python3 tools/pack_archive.py [<ref>]` packs a commit into such a kit (in `~/Downloads`); it needs Git LFS, since the archive carries the agent binaries.

## Features

- **Version-Aware Path**: Detects the installed CODESYS version and recommends the right `ScriptDir`. Newer CODESYS uses `%LOCALAPPDATA%\CODESYS\ScriptDir`; older CODESYS (before ~V3.5 SP17, e.g. 3.5.16) only scans `%PROGRAMDATA%\CODESYS\ScriptDir` — pick **[3] Legacy CODESYS** for those (may require administrator rights). With both kinds installed, the standard path [1] is recommended and the menu entry goes to the ProgramData path too (it shows once in the newer CODESYS); without administrator rights the installer prints the one command that adds it.
- **Path Selection**: Choose between the standard user path, the legacy machine-wide path, or a custom path for forks (KeStudio, DIA Designer, etc.).
- **Two Folders**: The tool is installed to a program folder (default `%LOCALAPPDATA%\cds-text-sync`) and only the `cds-text-sync` folder (the menu entry and the in-IDE agent) goes into `ScriptDir`. CODESYS scans `ScriptDir` recursively, so keeping the program out of it is what keeps the scripting menu down to the commands you use.
- **Migration**: An older installation sitting inside `ScriptDir` is moved out rather than copied, so untracked files of yours (`projects.json`) come along.
- **Version Control**: Interactive menu with the latest `main` branch, the last 5 stable releases, and the last 5 test / pre-release builds. A release up to 3.4.1, and `main` while it carries them, has no `cts.exe`: picking one runs that release's own installer (pick it again in its menu), after the agent folder is taken out of the menu folder; `projects.json` stays for a later update.
- **Auto-Update**: Detects existing versions, creates backups, and replaces files safely; your own files in the program folder (`projects.json`, which remembers each project's sync folder) are kept.
- **CLI Install**: Offers to add the bundled `cts.exe` folder to your user PATH.
- **Clean Install**: No `.git` history, minimal disk footprint (~5MB).

## Requirements

- **OS**: Windows 10/11
- **PowerShell**: 5.1 or higher
- **Internet**: Required for download
- **Git**: The installer checks that `git` is on PATH. Each project's sync folder is a git repository, so when git is missing it can offer `winget` installation or open the download page.

## CLI Command

The installer asks whether to add `<program-folder>\products\codesys-agent\dist` to your user PATH. Choose **Y** to run `cts` from new terminals:

```powershell
cts --help
cts ping --timeout 10
cts install --check   # the menu entry and the agent: anything out of date
```

## Alternative Installations (Forks)

If you use KeStudio, DIA Designer-AX, or another fork:

1. Select **Option 2** in the installer.
2. Provide your `ScriptDir` path (Shift + Right-click folder -> **Copy as path**).
3. See [Alternative Installations](../docs/alternative-installations.md) for details.
