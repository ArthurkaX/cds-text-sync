# cds-text-sync: Professional CODESYS Git Sync

**Version**: `2.0.1`

> [!IMPORTANT]
> **Disclaimer**: This is a third-party tool. It is NOT an official product of CODESYS Group and is not affiliated with, sponsored by, or endorsed by CODESYS Group. This tool is provided "as is" and is not a replacement for official CODESYS products.

Professional synchronization tooling for **CODESYS**. Version 2.0 is an XML-first rewrite: CODESYS exports a fresh Native XML snapshot, the external Python 3 engine builds the editable project view, and imports are applied back through targeted CODESYS text APIs plus native XML patches.

Custom object behavior and optional text projections are profile-driven; see [profiles/profiles.md](profiles/profiles.md).

### ⚡ External Editing & Sync (The "Developer" Workflow)

- **Goal**: Review and edit CODESYS projects with normal Git tools, external editors, and AI assistants.
- **Method**: `Project_export.py` writes generated snapshots to `.dump/` and editable files to the configured view root, usually `project-view/`.
- **Benefit**: XML remains the canonical round-trip format, while optional `.st` and `.csv` projections make code and translations readable in normal PR diffs.

For Zed users, [`PLC Structured Text`](https://github.com/ArthurkaX/zed-plc-structured-text) provides IEC 61131-3 Structured Text syntax highlighting for the generated `.st` / `.iecst` projections, focused on CODESYS-style PLC projects.

---

## 🚀 Key Features

- **XML-First Export**: `Project_export.py` captures `.dump/IDE.xml`, refreshes the configured view root, and writes `.dump/manifest.json`.
- **Compare Reports**: `Project_compare.py` captures `.dump/IDE.current.xml` and writes `.dump/compare_report.json` without changing the open project.
- **Interactive Review**: `Project_compare_ui.py` shows object-level changes in CODESYS, supports diff viewing, and can apply checked import/export actions.
- **Patch Import**: `Project_import.py` builds `.dump/IMPORT.xml` from disk edits and applies textual objects through CODESYS text APIs before native XML import handles the rest.
- **Completion Summaries**: Export and import show a final success popup by default, with an option to disable it in `Project_options.py`.
- **Pre-Import Backups**: Optional timestamped `.project` backups are written to `.backup/` before IDE-changing imports, with a configurable retention count.
- **Optional `.st` Projections**: POU, POU child, GVL, persistent variable list, task-local GVL, and DUT text can be emitted as readable `.st` files while duplicated text is removed from the XML sidecar for cleaner PR diffs.
- **Optional `.csv` Projections**: Text lists and alarm items can be exported as CSV and imported back for existing-row edits such as translation updates.
- **Profile-Aware Behavior**: JSON profiles describe vendor/fork-specific object kinds, projection availability, and safety rules.
- **Diagnostics**: `Project_build.py`, `Project_discover.py`, and `Project_resources.py` provide build, environment, profile, and snapshot-size diagnostics.
- **Legacy Isolation**: Older commands and the previous ST-oriented workflow are preserved under `old_scripts/` instead of being mixed into the active root command set.

---

## Requirements

- **Minimum Tested Target**: CODESYS V3.5 SP10+ (earlier versions might support scripting but lack essential API features for reliable text syncing).
- **Recommended Target**: CODESYS V3.5 SP13 and newer.
- **Python 3 Required**: Version 2.0 uses CODESYS/IronPython only as a thin IDE bridge. Export, compare, import, options, and diagnostics run the external Python 3 engine, so `python` must be available from the Windows command line.

Check before running the scripts:

```powershell
python --version
```

If this command is not found, install Python 3 or configure your environment so `python` points to Python 3.

The quick PowerShell installer also checks for `python` up front and can offer a manual download page or a `winget` installation path if it is missing.

---

## 🛠️ Installation

### Method 1: Manual Copy

1. **Copy Files**: Copy the root command scripts, `cds_bootstrap.py`, the entire `.runtime/` folder, and the entire `profiles/` folder to the CODESYS scripts directory.
   - **Note on `.pyw`**: Files inside `.runtime/` are internal runtime modules. They are hidden from the CODESYS "Scripts" menu by design.
   - **Note on `cds_bootstrap.py`**: This is a support loader used by the public `Project_*.py` entrypoints. Do not run it directly.

   Depending on your software and setup preference, use one of the following paths:
   - **Standard (User Profile)**: `C:\Users\<YourUsername>\AppData\Local\CODESYS\ScriptDir\`
   - **Standard CODESYS (Manual Setup)**: `C:\Program Files\CODESYS 3.5.18.40\CODESYS\ScriptDir\`
   - **Delta Industrial Automation (DIAStudio)**: `C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir`

   _(Note: You may need to create the `CODESYS`, `ScriptDir` folder manually if it doesn't exist)_.

### Method 2: Quick PowerShell Setup (Recommended)

Automate the installation and folder creation for Standard (User Profile) with one command:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!NOTE]
> - **No Git required**: This script downloads clean zip archives from GitHub, not the full repository with history.
> - **Choose version**: You can select the latest development version, a stable release, or a test / pre-release build from the interactive menu.
> - **Smaller footprint**: Installation downloads a clean script archive instead of cloning the full Git history.

> [!TIP]
> For a detailed explanation of what the script does, check the [Quick Setup Guide](irm/setup.md).

> [!TIP]
> Using a different CODESYS version or fork? See the [Alternative Installations Guide](ALTERNATIVE_INSTALLATIONS.md) for supported environments and installation paths.

2. **Access in CODESYS**:
   - The scripts will be available in **Tools > Scripting > Scripts > P**.

3. **Add to Toolbar (Recommended)**:
   - Go to **Tools > Customize > Toolbars**.
   - Add commands from **ScriptEngine Commands > P**.

   ![Add Button to Menu](img/add_button.gif)

---

## Upgrading from Previous Versions

When upgrading to a new version of `cds-text-sync`:

1. **Check Stable Releases**: First check if there's a newer stable release at [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
2. **Replace All Files**: Copy the full script payload again: root scripts, `cds_bootstrap.py`, `.runtime/`, and `profiles/`.
   - **Important Note**: If a major refactor (like shifting to shared libraries) occurs, active scripts held in CODESYS memory may become **stale**. After copying new files, it is best to restart CODESYS or reload your project to ensure the Script Engine picks up latest version of all modules.
3. **Clean Extract**: Run `Project_export.py` to refresh `.dump/IDE.xml`, the configured view root, and manifest data with the latest script logic.
4. **Commit Changes**: Review and commit the changes in Git.

> **Important for v2.0**: Version 2.0 uses the XML-first layout and requires Python 3. Run `Project_options.py` after upgrading, choose your layout/profile/projections, then run a clean `Project_export.py` before reviewing Git changes.
>
> **Tip**: A clean extract after upgrading ensures the exported XML views, projection files, and manifest data match the current engine behavior.
> 
> **Rollback**: If you encounter issues with a new version, see [Stable Releases & Rollback](#-stable-releases--rollback) section for how to safely revert to a previous stable version.

---

## 🎯 Stable Releases & Rollback

We maintain **stable, manually tested releases** for safe production use.

### Finding Stable Releases
- **GitHub Releases**: All stable releases are tagged and published on [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
- **Latest Tagged Version**: The most recent stable version is marked as "Latest Release"
- **Changelog**: See [CHANGELOG.md](CHANGELOG.md) for detailed change history

### Rolling Back to a Stable Version
If you encounter bugs in a newer version:

**Option 1: Git Rollback (Recommended)**
```bash
# Check available stable tags
git tag

# Rollback to specific stable version (e.g., v2.0.1)
git checkout v2.0.1

# Update your CODESYS scripts with the stable version
# Follow the installation steps to copy the files
```

**Option 2: Download from GitHub Releases**
1. Go to [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
2. Download the release archive for the stable version
3. Extract and copy the scripts to your CODESYS ScriptDir

> [!NOTE]
> You can also use the **Quick PowerShell Setup** script (Method 2 above) which automatically downloads stable releases as clean zip archives without requiring Git installation.

### Version Policy
- **Tags starting with `v`**: Official stable releases (e.g., `v2.0.1`, `v1.7.5`)
- **Main branch**: Latest development code (may be unstable)
- **Testing**: All stable releases are manually tested before tagging

> [!NOTE]
> Always backup your project before rolling back to a different version.

---

## 📖 Script Overview

### 1. `Project_directory.py` (Setup)

**Run this first.** It links your current CODESYS project to a sync root on disk.

![Setup Project Directory](img/setFolder.gif)

- Offers two options:
  - **Browse**: Select a folder using the file browser (traditional method).
  - **Manual Input**: Enter a path manually, supporting both absolute and relative paths.
- **Relative Path Support**:
  - Use `./` to sync to the same directory as your project file.
  - Use `./src/` or `./foldername/` to sync to a subfolder relative to your project.
  - **Perfect for team collaboration**: Relative paths work on any machine without reconfiguration, as they're resolved relative to the project file location.
  - The folder will be created automatically if it doesn't exist.
- Saves the sync-root path in the CODESYS project properties used by the active scripts.
- The selected sync root is then resolved into generated state such as `.dump/` and the editable view root such as `project-view/`.

**Examples**:

- Absolute path: `C:\MyProjects\MyPLC\sync\`
- Relative path (project directory): `./`
- Relative path (subfolder): `./sync/` or `./git-repo/src/`

### 2. Active Sync Commands

The active root entry points are `Project_directory.py`, `Project_options.py`, `Project_export.py`, `Project_import.py`, `Project_compare.py`, `Project_compare_ui.py`, `Project_build.py`, `Project_discover.py`, and `Project_resources.py`. Legacy commands referenced in older releases now live under `old_scripts/` and are not part of the primary workflow.

### 3. `Project_options.py` (Layout, Profile, Projections)

Use this after selecting the sync root.

- **View Storage**: Choose default `project-view/`, root-view, or an explicit custom view root.
- **View Root Lock**: Choose the view storage before the first export. After `.dump/manifest.json` has been created, `Project_options.py` locks the layout and custom view root controls. To use a different export folder, start again with a clean sync directory.
- **Profile**: Select the active CODESYS profile for object type handling.
- **Projections**: Enable optional readable files such as `.st` and `.csv` based on the active profile.
- **Safety Backup**: Enable or disable timestamped binary backup before import and set how many generated backups to keep.
- **Completion Summary**: Show or hide the final import/export success popup.
- **Git Ignore Helper**: Append recommended generated-state ignore rules without rewriting existing user rules.

### 4. `Project_export.py` (CODESYS -> Disk)

Exports the current project state into the XML-first workspace under the configured sync folder.

![Export Changes](img/Export.gif)

- **Fresh Snapshot**: Exports the live IDE project to `.dump/IDE.xml`.
- **Views Refresh**: Rebuilds the configured view root from the snapshot using the external Python 3 engine.
- **Manifest Update**: Writes `.dump/manifest.json` so later compare/import steps use the same exported object inventory.
- **Layout Guard**: Export, compare, and import fail with a clear error if the current view root does not match the manifest. This prevents duplicate editable folders after changing storage settings.
- **Offline-Friendly**: The heavy parsing and folder generation happen outside the IDE bridge.

### 5. `Project_import.py` (Disk -> CODESYS)

Applies disk changes back into CODESYS using the XML-first bridge.

- **Snapshot Before Change**: Captures a fresh `.dump/IDE.xml` before planning any import.
- **Patch Build**: Runs the external engine against the configured view root and prepares `.dump/IMPORT.xml`.
- **Safety Backup**: When enabled, saves the open project and copies the project binary to `.backup/YYYYMMDD_HHMMSS_<project-name>.bak` before applying a patch that changes the IDE.
- **Native Apply**: Textual objects are applied with CODESYS text APIs, then remaining non-textual XML is applied through native import.
- **Creates**: New standalone `.st` files can create supported text objects when the object kind is clear from the source.

### 6. `Project_compare.py` (IDE vs Disk)

Produces a report of differences between the current IDE state and the exported disk view.

![Compare and Interactive Sync](img/Compare-Import.gif)

- **Fresh Compare Snapshot**: Exports the current IDE state to `.dump/IDE.current.xml`.
- **View Baseline**: Compares that snapshot against the configured view root using the external diff engine.
- **Report Output**: Writes `.dump/compare_report.json` for diagnostics and follow-up review.

### 7. `Project_compare_ui.py` (Interactive IDE Compare)

- **Same Baseline**: Uses the same `.dump/IDE.current.xml` vs configured view root compare as `Project_compare.py`.
- **Object List**: Adds object names and paths to `.dump/compare_report.json` and shows them in a CODESYS dialog.
- **Actions**: Can launch import or export from the dialog. Checked objects can be applied selectively when the external engine can resolve them by GUID.

### 8. Optional Projections

Projections are editable views generated from XML-backed CODESYS objects. They are optional and selected in `Project_options.py`.

- **POU `.st`**: Declaration/interface first, then `// --- implementation ---`, then implementation.
- **POU children `.st`**: Methods, actions, properties, and accessors are emitted as flat sibling files such as `ST_FB.ST_METHOD.st`.
- **GVL, persistent variables, and DUT `.st`**: Global variables, persistent variable lists, task-local GVLs, and DUT declarations can be edited as text files.
- **TypeGuid metadata pragmas**: Ambiguous `.st` projections may start with `(* cds-text-sync: TypeGuid="{...}" *)`; this is a sync hint only and is stripped before XML rehydration or IDE text updates.
- **Text list `.csv`**: Existing `TextID` rows and language values can be edited for translation workflows.
- **Alarm item `.csv`**: Existing alarm rows can be edited by stable `AlarmID`.
- **Conflict Handling**: If both the redacted XML and its projection changed, compare/import fails explicitly instead of choosing a source silently.

CSV projections are update-only in this release. Inserted, removed, renamed, or duplicate rows fail explicitly. CODESYS supports only one Persistent Variables object per application, so creating a second one from a new `.st` file is rejected before IDE apply. Graphical implementations are skipped by profile safety rules unless a safe textual representation is available.

### 9. Diagnostics

- **`Project_build.py`**: Builds the active or selected application and writes `.dump/build_<Application>.log` plus `.dump/build_report.json`.
- **`Project_discover.py`**: Captures the live IDE tree and profile/type resolution into `.dump/discover_tree.log` and `.dump/discover_report.json`.
- **`Project_resources.py`**: Analyzes snapshot object sizes and categories, writing `.dump/resources_report.json` and `.dump/resources_top.log`.

### 10. Legacy Utilities

Older commands such as `Project_parameters.py` and the previous ST-oriented sync runtime are preserved in `old_scripts/` for historical reference only. They are not part of the active root-level command set.

---

## 🤝 Team Collaboration

For projects involving multiple engineers, we recommend a structured Git-based workflow.

- **[Detailed Team Workflow Guide](WORKFLOW.md)**: Learn how HMI/Hardware engineers and software developers can collaborate effectively using branches and Pull Requests.

---

## 🏗️ Project Structure

The tool organizes your repository into a clean structure:

```
/
├── project-view/            # Default Git-tracked editable XML/projection view
│   ├── .../*.xml            # Object XML views
│   └── .../*.st             # Optional text projections when enabled
├── .dump/                   # Generated operation workspace
│   ├── IDE.xml              # Latest full snapshot exported from CODESYS
│   ├── IDE.current.xml      # Compare-only live snapshot
│   ├── IMPORT.xml           # Generated patch for inject/import
│   ├── compare_report.json  # Machine-readable compare report
│   ├── build_<Application>.log # Build diagnostics for the selected/active app
│   ├── build_report.json    # Machine-readable build diagnostics
│   ├── sync_debug.log       # Verbose diagnostic log when file logging is enabled
│   └── manifest.json        # Exported object inventory and projection hashes
├── .backup/                 # Optional binary/safety backups
└── .diff/                   # Temporary files for external diff tooling
```

> [!TIP]
> For team review, track the configured view root (`project-view/` by default, or the sync root in root-view mode) and ignore generated state such as `.dump/`, `.backup/`, and `.diff/`.

`.backup/` is fixed by design. The options dialog controls whether pre-import backups are created and how many timestamped backups are retained; it does not let backups drift into the editable view root.

Example user-project `.gitignore` for the default `project-view/` layout:

```gitignore
.dump/
.backup/
.diff/
```

If `.st` projections are enabled, the exported `.xml` keeps CODESYS object metadata while `TextBlobForSerialisation` text is externalized into the `.st` file. This keeps normal Git and PR diffs focused on the readable text file instead of showing the same code change twice in XML and ST. During compare/import/validate, the engine rehydrates canonical XML from `.xml + .st`. For ambiguous textual object types such as persistent variable lists, the `.st` file may include a `(* cds-text-sync: TypeGuid="{...}" *)` pragma; the pragma is metadata for sync only and is never written back into CODESYS declarations. Text-list and alarm-item `.csv` projections are import-safe for editing existing rows only; inserted, removed, renamed, or duplicate rows fail explicitly.

---

## 🧠 Recommended Workflow with Git LFS

1.  **Configure**: Run `Project_directory.py` and point the project at the intended sync folder.
    - Run `Project_options.py` to choose the layout, profile, and optional projections such as `.st`.
    - Use the `.gitignore` option there to append the recommended generated-state ignore rules.
2.  **Extract**: Run `Project_export.py`.
    - The IDE snapshot goes to `.dump/IDE.xml`.
    - The reviewable export goes to the configured view root (`project-view/` by default).
3.  **Commit**:
    - `git add .`
    - `git commit -m "Update logic"`
    - Git tracks the view root and ignores generated state.
    - **Git LFS** may track binary backups if your team intentionally stores them.
4.  **Edit**: Make changes in VS Code or CODESYS.
5.  **Sync**: Run `Project_import.py`, `Project_export.py`, `Project_compare.py`, or `Project_compare_ui.py` depending on direction and whether you need a report or an IDE dialog.
    - `Project_import.py` applies disk changes back into the IDE.
    - `Project_compare.py` refreshes `IDE.current.xml` and writes a compare report.
    - `Project_compare_ui.py` shows the compare result and can launch full import/export.

### ❓ Why Git LFS for `.project`?

Since `.project` is a **binary file**, standard Git is not efficient at tracking its changes.

- **Prevents Bloat**: Normal Git stores the _entire file_ for every commit. If your project is 10MB, 100 commits would make your repo 1GB. LFS prevents this.
- **Performance**: You only download the binary version you are currently working on, keeping `git clone` and `git fetch` fast.
- **Code-Binary Sync**: It allows you to keep the full IDE state (visualizations, hardware config, generated snapshots) aligned with the exported disk view you review in Git.

> [!NOTE]
> Git LFS is **optional** and only needed if you want to version control your `.project` binary files. The `cds-text-sync` tool itself does not require Git to be installed for normal operation.

---

## 🧪 Reference Project & Examples

To keep this repository lightweight and minimalist for users who `git clone` the scripts, all test cases, problematic objects, and compatibility examples are hosted in a separate **[Reference Project](https://github.com/ArthurkaX/cds-text-sync-reference-project)**.

Refer to that repository's README for detailed verification procedures and contribution guidelines.

---

## 🗣️ Community & Future Roadmap

While Issues are great for reporting bugs, I invite you to join our **[GitHub Discussions](https://github.com/ArthurkaX/cds-text-sync/discussions)** for everything else! There you can suggest improvements and influence the development of the project.

---

## 📝 Changelog

See the full [CHANGELOG.md](CHANGELOG.md) for details on all versions.

For stable releases and download links, check [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases).

---

## 📜 License

MIT License.
