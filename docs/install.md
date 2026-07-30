# Installation

## Requirements

- **Minimum Tested Target**: CODESYS V3.5 SP10+ (earlier versions might support
  scripting but lack essential API features for reliable text syncing).
- **Recommended Target**: CODESYS V3.5 SP13 and newer.
- **Python 3 Required**: CODESYS/IronPython is used only as a thin IDE bridge.
  Export, compare, import, options, diagnostics, and the CLI use the external
  Python 3 engine, so `python` must be available from the Windows command line.

Check before running the scripts:

```powershell
python --version
```

If this command is not found, install Python 3 or configure your environment so
`python` points to Python 3. The quick PowerShell installer also checks for
`python` up front and can offer a manual download page or a `winget`
installation path if it is missing.

---

## Method 1: Quick PowerShell Setup (Recommended)

Automate the installation and folder creation for Standard (User Profile) with
one command:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!NOTE]
> - **No Git required**: This script downloads clean zip archives from GitHub,
>   not the full repository with history.
> - **Choose version**: You can select the latest development version, a stable
>   release, or a test / pre-release build from the interactive menu.
> - **Smaller footprint**: Installation downloads a clean script archive instead
>   of cloning the full Git history.

> [!TIP]
> For a detailed explanation of what the script does, check the
> [Quick Setup Guide](../irm/setup.md).

---

## Method 2: Manual Copy

Copy the full tool folder to the CODESYS scripts directory, including root
`Project_*.py` scripts, `cds_bootstrap.py`, `cli/`, `src/`, and `profiles/`.

- **Note on `.pyw`**: Files inside `src/` are internal runtime modules. They are
  hidden from the CODESYS "Scripts" menu by design.
- **Note on `cds_bootstrap.py`**: This is a support loader used by the public
  `Project_*.py` entrypoints. Do not run it directly.

Depending on your software and setup preference, use one of the following paths:

- **Standard (User Profile)**: `C:\Users\<YourUsername>\AppData\Local\CODESYS\ScriptDir\`
- **Legacy CODESYS (< ~3.5.17)**: `C:\ProgramData\CODESYS\ScriptDir\` — older
  CODESYS (e.g. 3.5.16) scans this machine-wide path, **not** the user profile
  one. May require administrator rights.
- **Standard CODESYS (Manual Setup)**: `C:\Program Files\CODESYS 3.5.18.40\CODESYS\ScriptDir\`
- **Delta Industrial Automation (DIAStudio)**: `C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir`

_(You may need to create the `CODESYS` and `ScriptDir` folders manually if they
don't exist.)_

> [!TIP]
> Using a different CODESYS version or fork? See the
> [Alternative Installations Guide](alternative-installations.md) for supported
> environments and installation paths.

---

## Install the CLI

The `cts` command is installed with Python packaging, from the folder you copied:

```powershell
python -m pip install -e <cds-text-sync-folder>
cts --help
```

This is what `cts`, the reverse-pipe daemon and [`cts visu`](visu.md) need. The
classic `Project_*.py` menu workflow works without it.

---

## After installing

1. **Access in CODESYS**: the scripts appear under
   **Tools > Scripting > Scripts > P**.
2. **Add to Toolbar (Recommended)**: go to **Tools > Customize > Toolbars** and
   add commands from **ScriptEngine Commands > P**.

   ![Add Button to Menu](../img/add_button.gif)

3. **Link a project to disk**: run `Project_directory.py`, then
   `Project_options.py`, then `Project_export.py`. See
   [Script overview](scripts.md) and
   [Recommended workflow](project-layout.md#recommended-workflow-with-git-lfs).

---

## Upgrading from previous versions

1. **Check stable releases**: first check whether there is a newer stable release
   at [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases).
2. **Replace all files**: copy the full tool payload again — root scripts,
   `cds_bootstrap.py`, `cli/`, `src/`, and `profiles/`.
   - **Important**: active scripts held in CODESYS memory may become **stale**
     after replacing files. Restart CODESYS or reload your project so the Script
     Engine picks up the latest modules.
3. **Clean extract**: run `Project_export.py` to refresh `.dump/IDE.xml`, the
   configured view root, and manifest data with the latest script logic.
4. **Commit changes**: review and commit the changes in Git.

> **Important when upgrading from pre-2.0 versions**: The current workflow uses
> the XML-first layout and requires Python 3. Run `Project_options.py` after
> upgrading, choose your layout/profile/projections, then run a clean
> `Project_export.py` before reviewing Git changes.
>
> **Tip**: A clean extract after upgrading ensures the exported XML views,
> projection files, and manifest data match the current engine behavior.
>
> **Rollback**: If you encounter issues with a new version, see
> [Releases & rollback](releases.md) for how to safely revert to a previous
> stable version.
