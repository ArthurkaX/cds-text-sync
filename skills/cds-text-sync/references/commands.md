# `cts` Command Selection

Use this reference as a routing guide. Confirm exact syntax with the installed `cts --help` and `cts <command> --help`.

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

Keep restore in dry-run mode unless the user explicitly requests application.

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
