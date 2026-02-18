# cds-text-sync

**Version**: `1.5.6`

> [!IMPORTANT]
> **Disclaimer**: This is a third-party tool. It is NOT an official product of CODESYS Group and is not affiliated with, sponsored by, or endorsed by CODESYS Group. This tool is provided "as is" and is not a replacement for official CODESYS products.

This repository contains a set of Python scripts for **CODESYS** that facilitate a modern Git-based workflow for PLC development.

### ⚡ External Editing & Sync (The "Developer" Workflow)

- **Goal**: Edit code using modern external tools (VS Code, Cursor, Copilot) and sync changes back to CODESYS.
- **Method**: Exports logic (POUs, GVLs, DUTs) to clean **Structured Text (.st)** files.
- **Benefit**: You can refactor code, use AI assistants, or mass-edit variables externally. The `Project_import.py` script then seamlessly updates your open CODESYS project.

---

## 🚀 Key Features

- **Reversible Sync**: Round-trip editing for Structured Text files.
- **Binary Backup (Git LFS)**: Optionally keeps a synchronized copy of your `.project` file for version control.
- **Timestamped Backups**: Automatically creates safety backups before imports to prevent data loss.
- **Native XML Export**: Optionally exports visualizations, alarms, and text lists to XML for diffing.
- **Safety**: Built-in checks (PC Name, Project Name) to prevent overwriting the wrong project.
- **Bi-directional Deletion**: Keep your file system and CODESYS project in sync by removing orphaned files.
- **Background Service**: A daemon that provides global hotkeys (`Alt+Q`) for quick actions without switching windows.

---

## � Requirements

- **Minimum Version**: CODESYS V3.5 SP10+ (earlier versions might support scripting but lack essential API features for reliable text syncing).
- **Recommended Version**: CODESYS V3.5 SP13 and newer.

---

## �🛠️ Installation

### Method 1: Manual Copy

1. **Copy Files**: Copy all `.py` files to the CODESYS scripts directory. Depending on your software and setup preference, use one of the following paths:
   - **Standard (User Profile)**: `C:\Users\<YourUsername>\AppData\Local\CODESYS\ScriptDir\`
   - **Standard CODESYS (Manual Setup)**: `C:\Program Files\CODESYS 3.5.18.40\CODESYS\ScriptDir\`
   - **Delta Industrial Automation (DIAStudio)**: `C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir`

   _(Note: You may need to create the `CODESYS`, `ScriptDir` folder manually if it doesn't exist)_.

### Method 2: Quick PowerShell Setup (Recommended)

Automate the installation, folder creation for Standard (User Profile), and Git configuration with one command:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!TIP]
> For a detailed explanation of what the script does, check the [Quick Setup Guide](irm/setup.md).

2. **Access in CODESYS**:
   - The scripts will be available in **Tools > Scripting > Scripts > P**.

3. **Add to Toolbar (Recommended)**:
   - Go to **Tools > Customize > Toolbars**.
   - Add commands from **ScriptEngine Commands > P**.

   ![Add Button to Menu](img/add_button.gif)

---

## � Upgrading from Previous Versions

When upgrading to a new version of `cds-text-sync`:

1. **Replace Script Files**: Copy the new `.py` files to your CODESYS scripts directory, overwriting the old versions.
2. **Clean Export**: Run `Project_export.py` to re-export all files with the updated format.
3. **Commit Changes**: Review and commit the changes in Git.

> **Tip**: A clean export after upgrading ensures all files use the latest export format and prevents inconsistencies.

---

## �📖 Script Overview

### 1. `Project_directory.py` (Setup)

**Run this first.** It links your current CODESYS project to a specific folder on your disk.

![Setup Project Directory](img/create_work_directory.gif)

- Offers two options:
  - **Browse**: Select a folder using the file browser (traditional method).
  - **Manual Input**: Enter a path manually, supporting both absolute and relative paths.
- **Relative Path Support**:
  - Use `./` to sync to the same directory as your project file.
  - Use `./src/` or `./foldername/` to sync to a subfolder relative to your project.
  - **Perfect for team collaboration**: Relative paths work on any machine without reconfiguration, as they're resolved relative to the project file location.
  - The folder will be created automatically if it doesn't exist.
- Saves the path (`cds-sync-folder`) and current machine name (`cds-sync-pc`) to **Project Information > Properties**.
- This binding ensures you don't accidentally sync to the wrong folder.

**Examples**:

- Absolute path: `C:\MyProjects\MyPLC\sync\`
- Relative path (project directory): `./`
- Relative path (subfolder): `./sync/` or `./git-repo/src/`

### 2. `Project_parameters.py` (Configuration)

**Configure how the sync works.** Runs an interactive menu to toggle options. Settings are saved in the project file.

- **[ ] Export Native XML**:
  - If ENABLED: visual objects (Visualizations, Alarms, ImagePools) are exported to `/xml` folder in PLCopenXML format.
  - Useful for tracking changes in non-textual objects.
- **[ ] Backup .project binary**:
  - If ENABLED: the script creates a copy of your `.project` file in the `/project` folder.
  - Essential for **Git LFS** workflows. Ensures your binary state matches your code state.
- **Set Backup Name**:
  - Allows you to specify a **fixed filename** for the binary backup (e.g., `Project`).
  - **Why use it?** If you often rename your `.project` files or work in a team where project names vary, setting a fixed name ensures the backup always overwrites the same file. This keeps your `/project` folder clean and prevents Git history from being cluttered with "new" files that are just renamed versions of the old ones.
- **[ ] Save Project after Import**:
  - If ENABLED: automatically saves the project after a successful import.
- **[ ] Timestamped Backup before Import**:
  - If ENABLED: creates a unique, timestamped `.bak` file in the `/project` folder _before_ starting the import process.
- **[ ] Silent Mode**:
  - If ENABLED: suppresses blocking popup messages and uses non-blocking system tray notifications (toasts).
  - Recommended for "Developer Workflow" to stay in flow.

### 3. `Project_export.py` (CODESYS -> Disk)

Exports the current project state to the sync folder.

- **Source Code**: Exports all POUs, GVLs, DUTs to `/src` as `.st` files.
- **Libraries**: Saves `_libraries.csv` for dependency tracking.
- **Binary Backup**: If enabled, saves the project and copies it to `/project`.
- **Cleanup**: Detects files on disk that no longer exist in CODESYS and offers to delete them.

### 4. `Project_import.py` (Disk -> CODESYS)

Updates the CODESYS project from the files on disk.

- **Smart Update**: Updates existing objects, creates new ones, and builds folder hierarchies.
- **Deletions**: If a file was deleted from disk, offers to delete the object from CODESYS.
- **Safety Backup**: If enabled, creates a timestamped project backup (`YYYYMMDD_HHMMSS_ProjectName.project.bak`) before modifying any code.
- **Binary Sync**: If "Backup .project binary" is enabled, it **automatically saves** the project after import and updates the binary backup, ensuring Git consistency.

### 5. `Project_Daemon.py` (Background Service)

**The ultimate productivity booster.** This script runs in the background and empowers you to control CODESYS from anywhere.

![Daemon Dashboard](img/Daemon.png)

- **Global Hotkey (Alt + Q)**: Open the Quick Action Dashboard from any application or virtual desktop.
- **Silent Operations**: Perform Exports, Imports, and Builds without interrupting your flow with popup dialogs.
- **Smart Focus**: The dashboard intelligently steals focus when activated and restores it to your previous window (e.g., VS Code) when done.
- **Build & Log**: Trigger a project build and get a clean, table-formatted `build.log` directly in your project folder.

**Usage**:

1. Run `Project_Daemon.py` once inside CODESYS to start it.
2. Press `Alt + Q` to toggle the menu.
3. Press `D` in the menu or run the script again to stop it.

- **Integration**: The specific error format allows external editors (like VS Code tasks) to parse the log and highlight errors in your original source files.

### 7. `Project_compare.py` (Object Comparison)

**Identify differences between IDE and Disk.** Compares the objects in your CODESYS project with the exported files on disk.

- **Detection**: Finds modified objects, new objects in IDE, and objects deleted from IDE.
- **Output**: Generates a detailed report in the Script Output window and saves it to `compare.log`.
- **Clean Run**: The `compare.log` file is recreated every time you run the script, ensuring you only see the latest results.
- **Daemon Integration**: Can be triggered directly from the Quick Action Dashboard ('C' key).

---

## 🤝 Team Collaboration

For projects involving multiple engineers, we recommend a structured Git-based workflow.

- **[Detailed Team Workflow Guide](WORKFLOW.md)**: Learn how HMI/Hardware engineers and software developers can collaborate effectively using branches and Pull Requests.

---

## 🏗️ Project Structure

The tool organizes your repository into a clean structure:

```
/
├── src/                  # The Logic Source. All .st files (POUs, GVLs, DUTs).
├── project/              # (Optional) The State Backup. Copy of .project for Git LFS.
├── xml/                  # (Optional) Native XML exports of Visualizations/Alarms.
├── config/               # Environment config (Libraries, TaskConfig).
├── sync_debug.log        # Diagnostic log for the last sync operation.
├── build.log             # Build output log.
├── compare.log           # Comparison results log.
├── _metadata.csv         # Split object metadata (Do not delete!)
├── _config.json          # Project configuration mirror.
└── _libraries.csv        # Library version tracking.

```

---

## 🧠 Recommended Workflow with Git LFS

1.  **Configure**: Run `Project_parameters.py` and enable **"Backup .project binary"**.
2.  **Export**: Run `Project_export.py`.
    - Code goes to `/src`.
    - Binary goes to `/project`.
3.  **Commit**:
    - `git add .`
    - `git commit -m "Update logic"`
    - Git tracks the text in `src/`.
    - **Git LFS** tracks the binary in `project/`.
4.  **Edit**: make changes in VS Code or CODESYS.
5.  **Sync**: Run `Project_import.py` or `Project_export.py` depending on where you edited.
    - The binary backup is automatically updated on every sync.

### ❓ Why Git LFS for `.project`?

Since `.project` is a **binary file**, standard Git is not efficient at tracking its changes.

- **Prevents Bloat**: Normal Git stores the _entire file_ for every commit. If your project is 10MB, 100 commits would make your repo 1GB. LFS prevents this.
- **Performance**: You only download the binary version you are currently working on, keeping `git clone` and `git fetch` fast.
- **Code-Binary Sync**: It allows you to keep the "full state" of the project (Visualizations, HW config) exactly matched with the "logic state" in `src/`.

---

## 📝 Changelog

### Version 1.5.6 (2026-02-18)

**Safety Net: Timestamped Import Backups:**

- **Automatic Rollback Point**: `Project_import.py` now creates a timestamped backup (e.g., `20260218_220000_MyProject.project.bak`) at the very beginning of the import process.
- **Configurable Safety**: Added "Timestamped Backup before Import" toggle in `Project_parameters.py` (enabled by default).
- **Non-destructive**: These backups are placed in the `/project` folder and use a `.bak` extension to avoid conflict with your primary Git LFS tracking.

### Version 1.5.5 (2026-02-18)

**Relative Path Support for Team Collaboration:**

- **Portable Project Configuration**: `Project_directory.py` now supports relative paths (e.g., `./`, `./folderName/`) in addition to absolute paths.
- **Manual Path Input**: Added a new "Manual Input" option in the directory setup dialog, allowing users to type paths directly.
- **Automatic Directory Creation**: If a specified directory doesn't exist, it will be created automatically.
- **Team-Friendly**: Relative paths are resolved relative to the project file location, making projects portable across different machines and users without reconfiguration.
- **Examples**:
  - `./` - Sync to project directory
  - `./sync/` - Sync to a subfolder
  - `C:\MySync\` - Traditional absolute path still supported

### Version 1.5.4 (2026-02-16)

**Comparison Logging & Rerouting:**

- **Dedicated Comparison Log**: `Project_compare.py` now reroutes its output to `compare.log` in the sync directory.
- **Recreative Logging**: The log file is truncated and recreated on every run, providing a fresh report for each comparison.
- **Tee Output**: Comparison results are still mirrored to the CODESYS Script Output window for immediate feedback.

### Version 1.5.3 (2026-02-16)

**Line Ending & Git Consistency Fix:**

- **Cross-Platform Consistency**: Fixed an issue where different line endings (CRLF vs LF) on different machines caused Git to show identical files as modified.
- **Deterministic Export**: The export script now explicitly uses LF (`\n`) for all `.st` files regardless of the host OS by using `newline=''` in file operations.
- **Automated Git Configuration**: Updated the `.gitattributes` template to automatically disable text conversion for `.st` files (`*.st -text`), ensuring they remain as LF in the repository and are treated consistently by Git on all platforms.

### Version 1.5.2 (2026-02-15)

**Improved Property Sync & Bug Fixes:**

- **Enhanced Property Support**: Properties with combined GET/SET accessors are now correctly handled. The export script now accurately combines both the `VAR` declaration and implementation code for each accessor into a single `.st` file.
- **Bi-directional Accessor Sync**: The import script now correctly parses combined accessor content and updates both the declaration and implementation in CODESYS.
- **Object Restoration**: Fixed an issue where objects deleted from CODESYS but remaining on disk would not be recreated. They are now automatically detected and restored during import.
- **Bug Fix (#4)**: Resolved an issue where properties created manually in external editors (or by AI) were incorrectly identified or failed to import.

### Version 1.5.1 (2026-02-15)

**Performance & Optimization Update:**

- **CRC32 Hashing**: Switched from SHA256 to CRC32 for file tracking, achieving **10-20x faster** hashing performance and significantly reducing metadata size.

### Version 1.5.0 (2026-02-13)

**The "Power User" Update:**

- **Project_Daemon.py**: New background service with Global Hotkey (`Alt + Q`).
- **Quick Action Dashboard**: Instant access to Export, Import, Build, and Backup commands.
- **Enhanced Build Log**: `Project_Build.py` now generates a clean, readable table format in `build.log` with accurate line numbers for external editors.
- **Focus Management**: Daemon correctly handles focus switching between Virtual Desktops and restores context after execution.

### Version 1.4.0 (2026-02-12)

**UI & Experience Overhaul:**

- **Configuration Dialog**: Replaced the text-based menu with a modern Windows Forms dialog for easier configuration.
- **Silent Mode**: Added a "Silent Mode" option that uses non-blocking system tray notifications (toasts) instead of blocking popups.
- **Safety**: Added checks to prevent sync on wrong machine (PC Name check).

### Version 1.3.0 (2026-02-09)

**Binary Backup & Configuration Overhaul:**

- **Project_parameters.py**: New interactive menu to toggle features.
- **Binary Backup**: Added optional `.project` file backup loop. The binary is now updated on both Export and Import events.
- **Logging**: Moved `sync_debug.log` to the project sync folder (or Temp) to keep `ScriptDir` clean.
- **Import Logic**: Removed interactive menu from Import script; now uses project settings.

### Version 1.2.0 (2026-02-09)

**Safety & Validation:**

- **PC Check**: Validates `cds-sync-pc` to prevent syncing on the wrong machine.
- **Properties**: All settings are now stored in Project Properties (`cds-sync-*`).

### Version 1.0.0 - 1.1.0

- Full support for nested folders.
- Detection of deletions (Orphan cleanup).
- Library version tracking (`_libraries.csv`).

---

## 📜 License

MIT License.
