# Project Layout

The tool organizes your repository into a clean structure:

```
/
├── project-view/            # Default Git-tracked editable XML/projection view
│   ├── .../*.xml            # Object XML views
│   └── .../*.st             # Optional text projections when enabled
├── .dump/                   # Generated operation workspace
│   ├── IDE.xml              # Latest full snapshot exported from CODESYS
│   ├── IDE.current.xml      # Compare-only live snapshot
│   ├── IMPORT.xml           # Generated patch for import/apply
│   ├── compare_report.json  # Machine-readable compare report
│   ├── build_<Application>.log # Build diagnostics for the selected/active app
│   ├── build_report.json    # Machine-readable build diagnostics
│   ├── sync_debug.log       # Verbose diagnostic log when file logging is enabled
│   ├── xml/                 # Text-first mode only: tool-owned structural XML mirror
│   └── manifest.json        # Exported object inventory and projection hashes
├── .backup/                 # Optional binary/safety backups
└── .diff/                   # Temporary files for external diff tooling
```

> [!TIP]
> For team review, track the configured view root (`project-view/` by default, or
> the sync root in root-view mode) and ignore generated state such as `.dump/`,
> `.backup/`, and `.diff/`.

`.backup/` is fixed by design. The options dialog controls whether pre-import
backups are created and how many timestamped backups are retained; it does not
let backups drift into the editable view root.

Example user-project `.gitignore` for the default `project-view/` layout:

```gitignore
.dump/
.backup/
.diff/
```

If `.st` projections are enabled, the exported `.xml` keeps CODESYS object
metadata while `TextBlobForSerialisation` text is externalized into the `.st`
file. This keeps normal Git and PR diffs focused on the readable text file
instead of showing the same code change twice in XML and ST. During compare and
import, the engine rehydrates canonical XML from `.xml + .st`. For ambiguous
textual object types such as persistent variable lists, the `.st` file may
include a `(* cds-text-sync: TypeGuid="{...}" *)` pragma; the pragma is metadata
for sync only and is never written back into CODESYS declarations. Text-list and
alarm-item `.csv` projections are import-safe for editing existing rows only;
inserted, removed, renamed, or duplicate rows fail explicitly.

---

## Recommended workflow with Git LFS

1. **Configure**: Run `Project_directory.py` and point the project at the
   intended sync folder.
   - Run `Project_options.py` to choose the sync mode, layout, profile, and
     optional projections such as `.st`.
   - Use the `.gitignore` option there to append the recommended generated-state
     ignore rules.
2. **Extract**: Run `Project_export.py`.
   - The IDE snapshot goes to `.dump/IDE.xml`.
   - The reviewable export goes to the configured view root (`project-view/` by
     default).
3. **Commit**:
   - `git add .`
   - `git commit -m "Update logic"`
   - Git tracks the view root and ignores generated state.
   - **Git LFS** may track binary backups if your team intentionally stores them.
4. **Edit**: Make changes in VS Code or CODESYS.
5. **Sync**: Run `Project_import.py`, `Project_export.py`, or
   `Project_compare_ui.py` depending on direction.
   - `Project_import.py` applies disk changes back into the IDE.
   - `Project_compare_ui.py` refreshes `IDE.current.xml`, writes a compare
     report, shows the result and can launch full import/export.

The same cycle from a shell: `cts export`, `cts compare`, `cts import`. See
[`cli/CLI.md`](../cli/CLI.md).

## Why Git LFS for `.project`?

Since `.project` is a **binary file**, standard Git is not efficient at tracking
its changes.

- **Prevents Bloat**: Normal Git stores the _entire file_ for every commit. If
  your project is 10MB, 100 commits would make your repo 1GB. LFS prevents this.
- **Performance**: You only download the binary version you are currently working
  on, keeping `git clone` and `git fetch` fast.
- **Code-Binary Sync**: It allows you to keep the full IDE state
  (visualizations, hardware config, generated snapshots) aligned with the
  exported disk view you review in Git.

> [!NOTE]
> Git LFS is **optional** and only needed if you want to version control your
> `.project` binary files. The `cds-text-sync` tool itself does not require Git to
> be installed for normal operation.
