# `cts` Command Selection

Use this reference as a routing guide. Confirm exact syntax with the installed `cts --help` and `cts <command> --help`.

## Guides

| Goal | Command |
|---|---|
| List the shipped operating guides | `cts guide` |
| Read the operating rules | `cts guide workflow` |
| Read a file shipped with a topic | `cts guide visu-svg --file examples/pid-schematic.svg` |

## Daemon and State

| Goal | Command |
|---|---|
| Check daemon liveness and cached PLC state | `cts ping` |
| Inspect daemon, project, sync folder, and PLC state | `cts status` |
| Configure the project sync folder through the daemon | `cts set-sync-folder [PATH] [--save]` |
| Read CODESYS IDE messages | `cts read-log` |
| Inspect daemon permissions | `cts permissions` |

## Folder and IDE Synchronization

| Goal | Command |
|---|---|
| Refresh projected files from the IDE | `cts export` |
| Compare the IDE with projected files | `cts compare` |
| Preview folder-to-IDE changes | `cts import --dry-run` |
| Apply folder-to-IDE changes | `cts import` |
| Apply and save the project | `cts import --save` |
| Apply without re-baselining the disk | `cts import --no-refresh` |
| Compile the active application | `cts build` |

Disconnect before import when the IDE is online with the PLC. Import has no online override flag; it is refused until the IDE is offline.

Import applies to the in-memory project and does not save — saving commits everything else open in the IDE, so it is the user's call. Report the `unsaved` warning when it appears; use `--save` only when the user asked for it. Import does re-baseline `project-view/` and `manifest.json` from the IDE, so the next compare is clean. When it withholds that refresh it says why in `manifest_refresh_skipped` — always because an edit did not reach the IDE and the disk still holds the only copy.

## Project Inspection and Object Changes

| Goal | Command |
|---|---|
| Read project metadata | `cts project-info` |
| Read the object tree | `cts project-tree` |
| Read an object | `cts read-object` |
| Update one POU from Structured Text | `cts update-pou` |
| Delete a POU, function, or function block | `cts delete-pou` |

Prefer full folder import for coordinated source changes. Use object-level mutation only when its narrower scope is intentional.

## PLC Lifecycle

| Goal | Command |
|---|---|
| Connect or log in | `cts connect` |
| Disconnect or log out | `cts disconnect` |
| Download the application | `cts download` |
| Start or stop the application | `cts start`, `cts stop` |
| Read application state | `cts app-state` |
| Compare PLC and local build CRC | `cts plc-crc` |
| Read or list the PLC runtime log | `cts plc-log [--file NAME] [--tail N]` |
| Extract generated `CTS\|` events as JSON | `cts plc-log --cts [--level M\|V] [--code CODE]` |

Check the installed command help for whether download also starts the application; do not encode that behavior as version-independent.

## Variables

| Goal | Command |
|---|---|
| Read one expression | `cts read` |
| Write one expression | `cts write` |
| Read multiple expressions | `cts read-vars` |
| Build an offline variable map | `cts variable-map` |
| Capture online values | `cts variable-snapshot` |
| Preview or apply a restore | `cts variable-restore` |
| List preset leaves | `cts snapshooter tree [--path PREFIX]` |
| Read a JSON preset | `cts snapshooter take [--path P] [--paths-file F] [--label L] [--out FILE]` |
| Diff a preset against the PLC | `cts snapshooter diff --input PRESET.json` |
| Restore a preset (dry-run unless `--apply`) | `cts snapshooter restore --input PRESET.json [--apply]` |
| Smoke-test the dialog headlessly | `cts snapshooter ui-check` |

Keep restore in dry-run mode unless the user explicitly requests application.

`variable-snapshot`/`variable-restore` move values as CSV through the offline
engine; `snapshooter` uses the dialog's own JSON preset format (`take` writes a
document of `{path, type, value, read_ok}` with a `meta` block, `diff`/`restore`
read it back) and needs a project open in the IDE.

### What each snapshooter action needs

| Action | Needs | Notes |
|---|---|---|
| `tree` | a project and `cds-sync-folder`; **no** PLC session | reads the exported declarations; no value is read |
| `take`, `diff`, `restore` | an existing **online session**, even in dry-run | they read live values; without a session the daemon answers `Not connected` — run `cts connect`, or log in in the CODESYS UI first (the daemon adopts a session but never logs in itself) |
| `ui-check` | a session where WinForms can be created | the form needs no online session; its `save`/`diff`/`restore` steps read live values, so without one they land in `failed_steps` |

Values are read through the online application's **symbols**, so a leaf that is
not exported (a struct/array member, an object not declared as a symbol, or code
not compiled into the PLC) comes back `read_ok: false` with *"is not exported to
the online application"* in `read_error` — that is a per-variable result, not a
command failure.

`--path` on `tree` is a **case-sensitive prefix** of the leaf path (not an exact
path, not a glob); `--path` on `take` is an exact path and is repeatable.

Every action's `--timeout` defaults to 300 s. The first call on a project also
exports `.dump/IDE.xml` and builds `.dump/snapshots/variable_tree.json` through
the CPython engine, which on a project with tens of thousands of leaves can take
over a minute on its own.

Output is one JSON object per action (`--pretty` renders it as text):

| Action | Envelope |
|---|---|
| `tree` | `{action, app, path, count, leaves[{path,type}]}` |
| `take` | `{action, app, label, count, document{meta,variables}, saved_to?}` |
| `diff` | `{action, app, count, report{same,missing,type_changed,value_changed}}` |
| `restore` | `{action, app, applied, result{written,skipped,warnings,would_write,details}}` |
| `ui-check` | `{action, report{ok,failed_steps,all_steps_ok,steps,windows,files,checked_leaves,leaf_count,parents}}` |

`ui-check` keeps exit code 0 when the report is delivered, including when steps
failed: a failed step is the finding it exists to report. Branch on
`report.all_steps_ok` / `report.failed_steps`; stderr echoes the failing names.
It does **not** check the window itself — the form is never shown, so layout,
fonts, resizing, focus and mouse behaviour are untested, and `MessageBox` and
the file dialogs are answering fakes.

### restore and the online session

`restore --apply` is caught between two gates that contradict each other:

* writing is refused while a session is cached — `restore(apply=True)` calls
  `ensure_snapshot_import_allowed` (`project_snapshooter.py`), which raises
  `Snapshot import is disabled while CODESYS is online` when
  `is_online_session_active()` sees a cached session;
* reading is refused without one — `restore` reads live values through `take`,
  and `read_variables_impl` calls `require_online_session`
  (`ide_online_helpers.py`), which raises `Not connected` when no cached or
  IDE-online session exists.

`--apply` therefore only gets through in the narrow window where the IDE is
online but the daemon has not cached the session yet (`is_online_session_active`
deliberately does not adopt a session; `require_online_session` does). The
daemon adopts an existing IDE session at startup, so in the ordinary case
`--apply` is blocked, and offline it fails on the read. This is reported, not
repaired.

To probe the guard and the write path without changing PLC state, restore a
preset whose entries all carry `read_ok: false`: `restore` skips every one with
`reason: source read_ok=false`, so `eligible` is empty and nothing is written
even with `--apply` — only the gate and the read are exercised.

### The diagnostic log

`<sync-folder>/.dump/snapshooter.log` receives lines only while the project
option **"Save detailed engine logs in .dump"** (`verbose_logging`) is enabled;
with it off the file stays empty or is not created at all (matching lines are
still echoed to the CODESYS scripting console). When no sync folder can be
resolved, the lines go to the system temp directory instead.

## Static Analysis

| Goal | Command |
|---|---|
| Run the offline analysis | `cts analyze` |
| List rules | `cts analyze rules` |
| Show one rule's docs | `cts analyze explain CTS0001` |
| Self-test rules | `cts analyze selftest` |
| Manage the baseline | `cts analyze baseline create\|update\|check` |
| Apply suppress/fix-later decisions | `cts analyze triage --apply decisions.json` |
| Validate generated visu XML | `cts visu-lint --xml file.xml` |

`cts analyze` runs offline over `project-view/` — it never talks to the daemon.
`--rule CTSxxxx` restricts to one rule (repeatable); `--fail-on` sets the exit-1
threshold (`danger`/`suspicious`/`style`); `--incomplete error` makes partial
runs exit 3. Exit codes: 0 passed, 1 findings at/above `--fail-on`, 2 config or
startup error, 3 incomplete. Some rules are opt-in and disabled by default. The
`cts-analyze.toml` config sets `[analyze] fail_on`/`incomplete`, `[rules.<ID>]
enabled`/`severity`/`options`, and `[[rule_scope]]`. State lives in
`.cts-analyze/` (baseline.json, suppressions.toml, session.json); source files
opt out with `// cts:ignore-file CTS0001 -- reason`.

## FSM Transition Maps

| Goal | Command |
|---|---|
| Scan the workspace for state machines | `cts fsm scan` |
| Render one file's machine | `cts fsm show` |
| Open the local FSM map window | `cts fsm ui` |

`cts fsm` runs offline over `project-view/` and never talks to the daemon.
`scan --query TEXT` filters files by case-insensitive relative-path substring
and `--json` emits exactly one JSON document; `show --file RELATIVE_PATH
--format json|mermaid|plantuml|svg` renders one machine and rejects paths that
escape the source root; `ui` opens a non-modal window and needs the optional UI
dependency (`pip install 'cds-text-sync[ui]'`). Exit codes: 0 means output
produced, including "no FSM found", and for `ui` the window opened and closed
normally; 2 means the command could not run (invalid workspace, bad path or
machine index, read/parse failure, or a missing UI dependency). Exit code 1 is
never used here — it already means "the analysis found something" for
`cts analyze`.

## Tests, Offline Engine, and Escape Hatch

| Goal | Command |
|---|---|
| Run JSON test plans | `cts test` |
| Run offline engine operations | `cts engine` |
| Call a daemon method directly | `cts raw` |

Inspect nested help before using these commands. Use `raw` only when the normal CLI does not expose the required supported operation.

## Output

- Default output is JSON and is suitable for parsing.
- Use `--pretty` or `--output text` for concise human-readable output.
- Preserve raw error details when reporting failures.
