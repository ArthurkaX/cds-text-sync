# Changelog

All notable changes to this project will be documented in this file.

---

### Version 1.6 (2026-02-24)

**Core Engine Refactoring & Interactive Sync:**

- **Multi-PLC & Multi-Application Support**: The engine now automatically handles complex project hierarchies, organizing exports into a clear `Device/Application/Folder` structure (essential for modern CODESYS projects).
- **Metadata-Free Sync Engine**: Significant refactoring to transition from metadata files (`_metadata.csv`, `_config.json`) to a direct, hash-based two-way comparison between the CODESYS IDE and disk. This improves reliability when moving projects between machines or using Git.
- **Interactive Comparison Dialog**: `Project_compare.py` now includes an interactive results window where you can selectively apply changes (Import or Export) directly from the diff list.
- **Project Discovery Tool**: New `Project_discover.py` script for mapping the project tree structure and diagnosing supported block types (logs findings to `sync_debug.log`).
- **Maintenance**: `Project_daemon.py` has been temporarily disabled.
- **Improved Comparison Logic**: Better handling of graphical POUs and XML-based objects (Visualizations, Task Configurations) in the comparison engine.

### Version 1.5.6.1 (2026-02-21)

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
