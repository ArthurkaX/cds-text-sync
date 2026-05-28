# Changelog

All notable changes to this project will be documented in this file.

---

### Version 2.5.1 (2026-05-28)

**CLI & Daemon:**

- Added the `cds-text-sync` CLI and reverse-pipe daemon workflow through `Project_daemon.py`.
- Added concise dashboard output for `rp cicd`: file-level PASS/FAIL plus suite summary.
- Changed the default CI/CD test folder from `test/` to `.test/`, with legacy `test/` fallback for existing projects.
- CI/CD plans now require an explicit `application` field so tests cannot silently run against the wrong application.
- Fixed `Project_options.py` runtime imports after moving the Python 3 engine to `cli/external_engine/`.
- Updated the recommended `.gitignore` entries for `.dump/`, reports, logs, backups, and temporary diff files.

**Installation & Documentation:**

- IRM installer now validates that `python --version` works and reports Python 3 before installing the CLI.
- IRM installer now offers to install the system CLI with `python -m pip install -e <install-path>`.
- Documentation now states that copying files into CODESYS `ScriptDir` does not install the `cds-text-sync` shell command.
- README and manuals refreshed for the CLI workflow, daemon demo, and test runner behavior.

**Infrastructure & Quality:**

- **GitHub Actions CI**: Added continuous integration workflow running tests on pushes and pull requests.
- **Node 24 Update**: CI actions updated to target Node 24 runtime.
- **Unit Test Tier**: Introduced structured unit test suite for external engine components.
- **Test Fixtures**: Unignored fixtures directory to include test data in version control.

**Security & Settings Window:**

- WinForms Settings window (poll frequency slider + permissions checkboxes)
- `rp permissions` — read-only config via CLI
- Storage in `cds-daemon-config` project property (JSON)
- Default deny list: reset_plc, create_boot_app, plc_upload, source_download
- Only the Settings window (not CLI) can change permissions
- Startup messages in dashboard (version + sync folder status)

**Fixes:**

- Stop Daemon no longer freezes CODESYS (Application.Exit, early loop break)
- Settings/Stop buttons swapped for ergonomics
- Sync folder warning on daemon start
- `run_external_engine()` path fixed to `cli/external_engine/`

**User Experience:**

- **Reference Compare Preview**: Validation now shows a reference comparison before applying changes.

**Documentation:**

- **Zed Extension**: Mentioned the Zed Structured Text extension for users who prefer the Zed editor.

### Version 2.0.1 (2026-05-11)

**Ambiguous Textual Object Projections:**

- **TypeGuid ST Pragmas**: Added `(* cds-text-sync: TypeGuid="{...}" *)` metadata pragmas for textual projections whose CODESYS object type cannot be reconstructed from ST syntax alone.
- **Persistent Variables Projection**: Persistent variable lists can now be exported and edited as `.st` projections while the sync pragma is stripped before XML rehydration and IDE text updates.
- **Profile-Driven GUID Policy**: Added `create_type_guids` and `ambiguous_text_type_guids` profile sections so special textual object handling is configured outside hardcoded syntax detection.
- **Textual Create TypeGuid**: `CreateTextObject` patch entries can now carry an explicit `TypeGuid`, preferred by the IDE bridge before built-in fallback GUID candidates.
- **Persistent Variables Safety Guard**: Creating a second Persistent Variables object in the same application is rejected before IDE apply because CODESYS supports only one such object per application.
- **IDE Bridge Cleanup**: Removed noisy create fallback diagnostics and the native XML template create fallback; existing textual objects are updated through available text documents even when CODESYS does not expose reliable `has_textual_*` flags.
- **Completion Summary Option**: Export and import now show a final success popup by default, with a project option to disable these completion summaries.

### Version 2.0.0 (2026-04-29)

**XML-First Synchronization Core:**

- **Native XML Snapshot Contract**: Reworked the sync flow around a fresh CODESYS Native XML snapshot for every export, compare, and import operation.
- **External Python 3 Engine**: Moved comparison, folder modeling, patch building, profile handling, and diagnostics out of the IDE bridge and into `src/external_engine/`.
- **Thin CODESYS Bridge**: Reduced IDE-side scripts to snapshot export, external engine dispatch, targeted text API updates, and native XML patch application.
- **Semantic XML Compare**: Added normalization for CODESYS serialization noise such as volatile timestamps, generated IDs, dictionary ordering, and whitespace.
- **Mixed Patch Application**: Textual POUs are now applied through CODESYS text APIs before native XML patch import handles remaining non-textual objects, preserving child method/action/property bindings.

**Public Script Set:**

- **User-Facing Commands**: Stabilized the public root entrypoints as `Project_directory.py`, `Project_options.py`, `Project_export.py`, `Project_import.py`, `Project_compare.py`, and `Project_compare_ui.py`.
- **Diagnostics Commands**: Added `Project_build.py`, `Project_discover.py`, and `Project_resources.py` for build checks, environment/type discovery, and snapshot resource analysis.
- **Hidden Engine Helpers**: Kept patch builders, project models, and runtime internals behind the `Project_*.py` scripts and external engine CLI.
- **Legacy Archive**: Preserved older scripts under `old_scripts/` for reference while making the new XML-first workflow the active path.

**Project Layout & Settings:**

- **Project Settings File**: Added tracked `cds-text-sync.json` support for layout, profile, and projection choices.
- **View Root Modes**: Added support for legacy `.dump/views`, default `project-view/`, explicit `--view-root`, and experimental root-view mode.
- **Generated State Separation**: Standardized generated folders around `.dump/`, `.backup/`, and `.diff/`, with stale managed files cleaned by manifest ownership.
- **Options UI**: Reworked `Project_options.py` so users can choose layout, active CODESYS profile, and optional derived text projections from a dialog.
- **Pre-Import Safety Backups**: Added optional timestamped `.project` backups before IDE-changing imports, stored only in `.backup/` with retention cleanup.

**Optional Text Projections:**

- **Readable POU `.st` Views**: Added opt-in `.st` projections for POU text with declaration first, `// --- implementation ---`, and implementation second.
- **Flat Child POU Files**: Added `.st` projections for methods, actions, properties, and accessors as sibling files such as `ST_FB.ST_METHOD.st`.
- **DUT `.st` Views**: Added declaration-only `.st` projections for DUT objects such as structures, enums, unions, and aliases.
- **Standalone `.st` Creates**: Added controlled creation of new text objects from standalone `.st` files when the semantic kind can be detected.
- **Text List CSV**: Added import-safe CSV projections for TextList objects, limited to editing existing rows and translations.
- **Alarm Item CSV**: Added import-safe CSV projections for alarm items, limited to existing alarm row updates.
- **No Duplicate PR Diffs**: When projections are enabled, export externalizes owned text into `.st` or `.csv` and redacts the duplicate text from the XML sidecar.
- **Projection Conflict Detection**: Compare/import now fail explicitly when both canonical XML and its derived projection changed since the last export.

**Compare & Review Workflow:**

- **Interactive Compare UI**: Added checkbox review, object metadata, and disk-vs-IDE diff viewing through `Project_compare_ui.py`.
- **Projection-First Diffs**: Compare UI prefers `.st` or `.csv` diffs when a projection owns the edited text, while keeping XML available for fallback cases.
- **Selected Actions**: Added filtered import/export support by GUID so Compare UI can apply only checked objects.
- **Large Project Stability**: Reduced compare report memory pressure and avoided flooding IDE output with repeated missing-resource messages.

**Diagnostics & Large Project Support:**

- **Build Diagnostics**: `Project_build.py` builds the active or selected application and writes `.dump/build_<Application>.log` plus `.dump/build_report.json`.
- **Discover Diagnostics**: `Project_discover.py` records live IDE tree/type information into `.dump/discover_tree.log` and `.dump/discover_report.json`.
- **Resource Diagnostics**: `Project_resources.py` analyzes snapshot object sizes and categories, writing `.dump/resources_report.json` and `.dump/resources_top.log`.
- **Missing External Resource Skip**: Snapshot export skips missing image/file-like resources that can block CODESYS native export on large projects.

**Known Limitations:**

- Visualization objects can report native import success while specific visual property edits are not applied by CODESYS; this remains a targeted investigation area.
- CSV projections are update-only in this release: inserted, removed, renamed, or duplicate rows fail explicitly.
- Graphical CFC/FBD/LD implementations are intentionally excluded from `.st` projections unless a profile explicitly marks a safe textual representation.

### Version 1.7.5 (2026-04-17)

**Profiles, Semantic Kinds & Sync Policy:**

- **JSON Type Profiles**: Added profile files in `profiles/` with inheritance, `guid_aliases`, `context_rules`, `sync_profile_overrides`, and `sync_direction_overrides` so projects can remap, merge, force XML handling, or skip types without code changes.
- **Semantic-First Type Resolution**: Completed the migration from scattered GUID checks to centralized semantic kind resolution, making object classification more consistent across export, compare, import, and discovery.
- **Per-Type Direction Control**: Added `bidirectional`, `export_only`, `import_only`, and `disabled` sync direction policies per semantic kind.
- **Library Manager as Export-Only**: `library_manager` now exports for Git visibility and diffing, but is skipped on import to avoid unreliable placeholder restoration.
- **Hardware Policy in Profiles**: `device` and `device_module` are now controlled by profile settings instead of hardcoded skips, using `native_xml` + `export_only` by default.
- **Profile Documentation**: Reworked profile docs into `profiles/profiles.md` and added a reusable `profiles/template.json`.

**Runtime Architecture & Entry Points:**

- **Internal Runtime Extraction**: Moved internal engine modules into `.runtime/` and reduced the top-level `Project_*` scripts to thin entrypoints.
- **Shared Bootstrap Layer**: Centralized runtime loading into a shared bootstrap module and renamed the public bootstrap entrypoint to `cds_bootstrap.py`.
- **Automation-Friendly Script Calls**: Updated the main entry scripts so they can be invoked more cleanly by external tooling and scripted workflows.

**Compare/Import Robustness:**

- **Nested ST Import Order Fix**: Import now sorts textual files so parent POUs are created before nested children like `TaskMain.Method.st`, fixing first-pass import into empty projects.
- **Shared Native XML Snapshot Path**: Export and compare now use the same native XML snapshot builder and the same recursion policy for XML-based objects.
- **Reduced False Hardware Diffs**: Folder hash invalidation is now limited to the direct parent folder, preventing one `.st` edit from forcing untouched `device` and `task_config` objects into noisy XML re-compare.
- **Cache Recovery for Exported Objects**: Added export-side cache backfilling and better cache warnings so successfully exported objects are less likely to disappear from `sync_cache.json` bookkeeping.
- **More Explainable Compare Logging**: Compare now logs the exact reason an object dropped into slow-path XML comparison.

**Logging, UI & Runtime Noise Reduction:**

- **Toggleable File Logging**: Added a project setting to enable or disable file logging and updated ignore patterns accordingly.
- **Quieter Compare/Import/Export Output**: Reduced console/log spam in normal workflows and removed compare log teeing to `compare.log`.
- **Settings Dialog Cleanup**: Refined the Settings UI layout and grouping for a cleaner configuration flow.
- **Unsupported Build Property Silence**: Missing `build_properties` members such as `external_implementation` are now skipped quietly instead of spamming `INFO`/`WARNING` for every object.
- **Python 3 Compatibility Cleanup**: Replaced deprecated `callable()` usage in runtime diagnostics with a Python-3-compatible check.

### Version 1.7.4 (2026-04-11)

**Attribute Synchronization (DRY Sync):**

- **Pragma-Based Metadata**: Implemented a new synchronization system for IDE-specific attributes (e.g., "Exclude from build", "Link always") using `//% cds-text-sync.key=value` pragmas directly in `.st` files.
- **CODESYS API Fixes**: Resolved issues with attribute access by correctly utilizing the `obj.build_properties` (ScriptBuildProperties) API for reading and writing IDE flags.
- **Bi-directional Sync**: Ensured that removing a pragma from the source file correctly clears the corresponding attribute in the IDE during import.
- **Cache Integrity**: Updated the quick hashing logic to include object attributes, ensuring that toggling IDE flags correctly invalidates the cache and triggers a re-export.
- **Comparison UI Enhancement**: The built-in diff viewer now renders IDE attributes as pragmas, allowing users to see and review metadata changes alongside code changes.
- **Cache Migration**: Bumped `CACHE_VERSION` to `3.1` to force a clean state rebuild and ensure all objects are tracked with attribute-aware hashes.

### Version 1.7.3 (2026-04-02)

**Move/Rename Detection & Stale File Cleanup:**

- **Moved File Detection**: Implemented smart detection of renamed/moved project files by cross-referencing IDE orphan objects with disk orphan files using base filename matching.
- **Automatic Path Invalidation**: Enhanced cache invalidation logic to detect when objects are moved/renamed in the IDE, ensuring stale cached paths are refreshed during comparison.
- **Stale File Cleanup**: Added automatic removal of old files from disk during export when objects have been moved/renamed in the IDE, preventing orphaned files from cluttering the sync directory.
- **UI Enhancements**: Updated comparison dialog to display moved files with their old (IDE) and new (Disk) paths, using `~moved` visual indicator.
- **Import/Export Move Handling**: Added logic to physically move objects within the IDE during import when path mismatches are detected, ensuring project structure stays synchronized.
- **Statistics Update**: Moved object count now reported in comparison summary (`~:` prefix) and import/export completion messages.

### Version 1.7.2 (2026-03-28)

**Critical Fixes & UX Optimization:**

- **Module Import Fix**: Resolved a critical `ImportError` where `codesys_ui` was not being loaded in `Project_directory.py`, causing a crash on startup for new projects.
- **Reference Bug Fixes**:
  - Fixed an undefined variable crash (`choice[0]`) in `Project_directory.py`.
  - Fixed an undefined variable crash (`result[0]`) in `Project_export.py` during orphaned file cleanup.

### Version 1.7.1 (2026-03-27)

**UI Robustness & Post-Sync Enhancements:**

- **Standard Windows Prompts**: Replaced the unreliable native CODESYS `system.ui.choose` radio-button dialogs with standard Windows MessageBox dialogs (`ask_yes_no`, `ask_yes_no_cancel`) across all scripts.
- **Cancel Button Fix**: Completely resolved an issue where clicking "Cancel" or closing dialogue windows would fail to halt script execution due to inconsistent CODESYS API return types.
- **Import Final Confirmation**: Added an explicit final summary dialog (`Ready to import X changes into the IDE... Proceed?`) right before applying structural changes or deletions in `Project_import.py`.
- **Auto-Save & Workflow**:
  - Introduced optional automatic project saving and binary backup after an export is completed.
  - Added a new 'Save Project after Export' toggle in the Configuration UI (`Project_parameters.py`).
  - Centralized version compatibility checks, safety backups, and post-sync operations into `codesys_utils.pyw` for cleaner architecture and standardized execution.

### Version 1.7.0 (2026-03-27)

**Merkle Tree & High-Performance Sync Overhaul:**

- **Lightning-Fast Comparison**: Total sync/compare time reduced by ~90% (sub-10s for large projects) using a new Merkle Tree-based hierarchical hashing strategy.
- **Intelligent Path/Type Caching**:
  - Implemented GUID-based caching for object classification and filesystem paths in `sync_cache.json`.
  - Eliminates thousands of slow CODESYS COM API calls (`classify_object`, `get_children`, `build_expected_path`) on repeat runs.
- **Hierarchical Merkle Skips**: The comparison engine now uses folder hashes to skip entire unchanged branches of the project tree instantly.
- **Import Optimization**:
  - Eliminated redundant double-save operations during import/backup, reducing the post-import pause by 50%.
  - Optimized POU child restoration and metadata handling.
- **Hybrid XML Hashing**: Integrated last-known XML hashes into Pass 1 so folders containing mixed ST and XML objects can still benefit from Merkle Tree skips.
- **Integrated Accessor Collection**: Merged property accessor scanning into the main object pass to avoid redundant project-wide traversals.
- **Profiling Tool Upgrade**: Updated `Project_perf_test.py` with the new architecture to provide accurate real-world metrics, including cache hit ratios and Merkle skip statistics.

---

### Version 1.6.7 (2026-03-25)

**Silent Mode Removal & Backup Enhancement:**

- **Removed Silent Mode**: All `silent` parameters have been removed from `Project_import.py`, `Project_export.py`, `Project_compare.py`, and `Project_Build.py`. Scripts now consistently use modal dialogs for all user feedback.
- **Unified UI Behavior**: All operations now use modal dialogs (`system.ui.info` / `system.ui.error`) in interactive mode, eliminating the previous inconsistent behavior.
- **Version Compatibility Checks**: All version compatibility checks now always prompt the user when version mismatches occur, rather than silently logging warnings or ignoring the issue.
- **Timestamped Backup with Retention**: Enhanced import backup functionality with automatic retention policy:
  - **codesys_utils.pyw**: Added `cleanup_old_backups()` function to automatically delete old timestamped backups while preserving non-timestamped Git LFS backups
  - **Enhanced Backup Function**: `backup_project_binary()` now accepts `retention_count` parameter and returns the backup filename on success
  - **UI Enhancement**: Added "Max Backups to Keep (Optional)" field in settings dialog (default: 10, minimum: 1)
  - **Persistent Settings**: Added `cds-sync-backup-retention-count` property to Project_parameters.py for cross-run persistence
  - **Import Scripts**: Both `Project_import.py` and `Project_compare.py` now create timestamped backups before import operations when changes exist
  - **Backup Reports**: Import completion reports now show backup confirmation message when safety backups are created
  - **Cleanup Pattern**: Only timestamped `.bak` files matching pattern `^\d{8}_\d{6}_.*\.bak$` are subject to cleanup; non-timestamped backup files are preserved

---

### Version 1.6.6 (2026-03-18)

**Resource Analysis UI Enhancement:**

- **Interactive Results Dialog**: `Project_resources.py` now displays results in a modern Windows Forms dialog instead of console output.
- **Sortable Data Grid**: Click column headers to sort by Object Name, Type, Size, or Category.
- **Full Object List**: Shows all analyzed objects with scrolling support (previously limited to top 30).
- **Summary Panel**: Displays Total Code, Total XML, and Object count at the bottom.
- **Fallback Support**: Console output still works if UI components are unavailable.

---

### Version 1.6.5 (2026-03-17)

**Interface Export Support:**

- **Interface Objects**: Added full support for exporting and importing `INTERFACE` objects with their `EXTENDS` clauses preserved.
- **Interface Methods**: Interface methods/properties now export as flat files (`InterfaceName.Method.st`) matching the existing FB pattern.
- **Native XML Fallback**: Added `export_interface_declaration()` function that extracts interface declarations via native XML export when `textual_declaration` is unavailable.
- **Updated Type GUIDs**: Corrected interface type GUID to `6654496c-404d-479a-aad2-8551054e5f1e` and added `itf_method` GUID for interface members.

---

### Version 1.6.4 (2026-03-12)

**UI Cleanup & Module Security:**

- **Hidden Internal Modules**: Renamed all `codesys_*.py` files to `.pyw` extension. This hides them from the CODESYS Script Engine menu, providing a cleaner user interface that only shows primary `Project_*.py` commands.
- **Custom Module Loader**: Implemented a robust `_load_hidden_module` mechanism in all entry scripts to handle `.pyw` imports with proper dependency ordering.
- **Deprecated Scripts Cleanup**: Removed several unused and debug scripts (`debug_metadata.py`, `Project_Daemon.py`) to streamline the repository.

---

### Version 1.6.3 (2026-03-07)

**Version Tracking & Compatibility Detection:**

- **Single Source of Truth**: Added `SCRIPT_VERSION = "1.6.3"` in `codesys_constants.py` as the central version reference for all scripts.
- **Dual Storage Strategy**:
  - **sync_metadata.json**: Metadata file stored in export directory containing script version, last action (export/import), timestamp, duration, and statistics.
  - **Project Property**: Version also saved to CODESYS project property (`cds-sync-version`) for runtime compatibility checks.
- **Import/Compare Warnings**: Both `Project_import.py` and `Project_compare.py` now detect version mismatches and display warnings without blocking operations (User can continue at their own risk).
- **Improved Audit Trail**: Each export and import operation updates `sync_metadata.json` with current script version, making it easy to identify which scripts were used for operations.
- **Git Integration**: The `sync_metadata.json` file is now tracked in version control, enabling teams to see export/import history.

---

### Version 1.6.2 (2026-03-04)

**XML Import & Object Structure Enhancements:**

- **POU Child Management**: Implemented saving and restoring of POU children during the XML import process to maintain project hierarchy.
- **Parent Lookup**: Enhanced parent POU lookup logic during object creation for improved structural accuracy.
- **Empty Implementation Handling**: Ensured that implementation markers are always present for specific object types, even if their implementation is empty (addressing issues where empty methods or properties might be skipped).

### Version 1.6.1 (2026-02-26)

**Orphan Deletion & Stability Enhancements:**

- **Bi-directional Orphan Management**:
  - **IDE-to-Disk (Sync/Export)**: Existing logic in `Project_export.py` continues to clean up files on disk that are missing in the IDE.
  - **Disk-to-IDE (Import)**: `Project_import.py` now supports deleting objects from the IDE if they were removed on disk (e.g., from a Git pull). The "Disk wins" principle is now fully enforced.
- **Improved Comparison UI**:
  - The Interactive Results dialog now clearly identifies objects missing on disk as **"Missing on Disk (DELETE from IDE?)"**.
  - Importing these items will now safely remove them from the CODESYS project tree.
- **Hardware Stability (Device Exclusion)**:
  - Hard-excluded `device` and `device_module` objects from the synchronization engine.
  - Syncing these components via XML was found to be unstable (can lead to tree reconstruction and project "emptying").
  - Users should configure hardware manually and sync the application logic.
- **Bug Fixes**:
  - Fixed an issue where the import process could fail to report the correct number of updated/created items when deletions were involved.
  - Updated default `.gitignore` template to include `*.device` and `*.device_xml` patterns as a safety measure.

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
- **Bug Fix (#4)**: Resolved an issue where properties created manually in external editors were incorrectly identified or failed to import.

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
