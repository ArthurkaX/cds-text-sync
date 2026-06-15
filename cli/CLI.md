# cds-text-sync CLI

This document is the command contract for the simplified `cds-text-sync` CLI.
The CLI has one normal transport: it talks to `Project_daemon.py` running inside
CODESYS. The old `rp` spelling is only a compatibility alias for raw daemon
commands.

## Startup

A human starts the bridge once per CODESYS session:

1. Open the project in CODESYS.
2. Run `Project_daemon.py` from Tools -> Scripting -> Execute Script.
3. Keep the daemon dashboard open while using the CLI.

Install the console command with:

```bash
python -m pip install -e .
```

Both console names are installed:

```text
cts
cds-text-sync
```

The short `cts` spelling is used in examples.

Then check the daemon:

```bash
cts ping --timeout 10
cts status --timeout 10
```

`stdout` is JSON by default. Human diagnostics go to `stderr`.

Use text output when reading results manually:

```bash
cts --output text status
```

## Main Sync Commands

These are the primary commands for editing CODESYS projects as text.

| Command | Direction | Meaning | Timeout |
| --- | --- | --- | --- |
| `status` | daemon -> CLI | Show daemon, project, and sync-folder state. | 10s |
| `export` | IDE -> disk | Export the open IDE project and overwrite `project-view/`. | 60s |
| `compare` | IDE vs disk | Compare the open IDE project against `project-view/`. | 60s |
| `import` | disk -> IDE | Build `IMPORT.xml` from `project-view/` and apply it to the IDE project. | 120s |

Normal edit cycle:

```bash
cts export --timeout 60
# edit files in project-view/
cts compare --timeout 60
cts import --timeout 120
cts build --timeout 120
```

`import` options:

| Flag | Meaning |
| --- | --- |
| `--dry-run` | Show what would change without applying (runs compare). |
| `--force-online` | Skip the offline preflight check; use only when you are sure the IDE is offline. |

Rules:

- `export` is destructive for local text files: it refreshes `project-view/`
  from the IDE state.
- `import` treats disk as the source of truth.
- Adding new objects requires the IDE project to be offline. Run
  `disconnect` before `import` when new GVL, DUT, POU, or folder objects were
  added on disk. If `disconnect` does not clear the online state, use
  `cts import --force-online` or `cts raw sync_import_text force_online=true`.
- `build` compiles in the IDE only. It does not guarantee that the PLC is
  running the new code.

## Build And PLC Commands

| Command | Meaning | Requires | Timeout |
| --- | --- | --- | --- |
| `build` | Compile the active application in the IDE. | daemon | 120s |
| `connect [--ip IP]` | Login/connect to the configured PLC or explicit IP. | daemon + device | 60s |
| `disconnect` | Logout from the PLC. | daemon | 15s |
| `download [--start 0|1]` | Force a full download to PLC. Use after adding new objects. | online/device | 120s |
| `start` | Start PLC application. | online | 25s |
| `stop` | Stop PLC application. | online | 25s |
| `app-state` | Show application run/stop/login state. | daemon | 10s |
| `plc-crc` | Compare PLC `Application.crc` with the local IDE build output. | online | 30s |

Deploy existing online-changeable edits:

```bash
cts import --timeout 120
cts build --timeout 120
cts connect --timeout 60
cts plc-crc --timeout 30
```

Deploy newly added objects:

```bash
cts disconnect --timeout 15
cts import --timeout 120
cts build --timeout 120
cts download --timeout 120
cts plc-crc --timeout 30
```

`plc-crc --build` will build the project first, then compare CRCs.

```bash
cts plc-crc --build --timeout 120
```

`connect` uses the normal CODESYS login flow. If the change cannot be handled
as an online change, use `download`.

## Variables

| Command | Meaning | Requires |
| --- | --- | --- |
| `read NAME` | Read one online variable/expression. | online |
| `write NAME VALUE` | Write one online variable/expression and read it back. | online + permission |
| `read-vars EXPR... [--file FILE]` | Batch-read expressions. | online |
| `variable-map` | Build an offline CSV map from `project-view/`. | exported project-view |
| `variable-snapshot` | Read live values for mapped scalar leaves to CSV. | online |
| `variable-restore --input FILE [--apply]` | Restore values from a snapshot CSV. Dry-run by default. | online + permission |

Examples:

```bash
cts read MAIN.fbArith.rResult --timeout 25
cts write GVL_HMI.HMI_start TRUE --timeout 25
cts read-vars MAIN.a MAIN.b --timeout 30
cts variable-map --path GVL_HMI
cts variable-snapshot --path GVL_HMI --out snap.csv --timeout 120
cts variable-restore --input snap.csv --apply --timeout 120
```

## Tests

`test` runs JSON test plans against the online PLC application.

```bash
cts test --file arithmetic.json --timeout 120
cts test --timeout 120
```

Plans live in `<sync-folder>/.test/`. If `--file` is omitted, all `*.json`
plans are executed in sorted order. See [TEST_FORMAT.md](TEST_FORMAT.md) for the
JSON schema and examples.

## Project And Object Tools

These commands are useful for diagnostics and targeted maintenance, but they
are not part of the normal edit cycle.

| Command | Meaning |
| --- | --- |
| `project-info` | Show open project metadata, Summary fields, and all Project Information properties. |
| `project-tree [--depth N]` | Show the CODESYS project object tree. |
| `read-object [--path PATH] [--name NAME] [--guid GUID]` | Read one project object. `--name` is the most reliable selector. `--path` uses forward slashes, e.g. `Application/MAIN`. GUIDs from `project-tree` may not match IDE GUIDs. |
| `update-pou --name NAME --st-path PATH [--app APP]` | Update one textual POU from an `.st` file. |
| `delete-pou NAME [--app APP]` | Delete a Program, Function, or Function Block. Permission-gated. |
| `read-log [--last N] [--clear]` | Read CODESYS IDE messages. |
| `permissions` | Show daemon permission settings. Read-only from CLI. |

Prefer `import` over `update-pou` for normal work. `update-pou` is an escape
hatch for single-object repairs.

## Raw And Engine Escape Hatches

The normal CLI should cover everyday use. These commands exist for compatibility
and debugging.

| Command | Meaning |
| --- | --- |
| `raw METHOD [--key value ...]` | Send a daemon method directly. Useful for overrides such as `force_online=true` or a custom `timeout`. |
| `rp METHOD [--key value ...]` | Deprecated alias for `raw`. |
| `engine export|import|compare|validate|resources ...` | Run `engine_cli.py` directly without CODESYS. |

Examples:

```bash
cts raw help --timeout 10
cts raw application_tree --flat --output C:/Temp/tree.json --timeout 120
cts raw sync_import_text force_online=true --timeout 120
cts engine validate --project-root C:/Work/Project
```

Raw daemon names are implementation details. Do not use them in new scripts
when a top-level command exists.

## Command Mapping

The simplified CLI maps to daemon methods as follows:

| CLI command | Daemon method |
| --- | --- |
| `ping` | `ping` |
| `status` | `status` |
| `export` | `sync_export_text` |
| `import` | `sync_import_text` |
| `compare` | `sync_compare_text` |
| `build` | `build` |
| `connect` | `connect_to_device` |
| `disconnect` | `disconnect_from_device` |
| `download` | `download` |
| `start` | `start_plc` |
| `stop` | `stop_plc` |
| `app-state` | `application_state` |
| `plc-crc` | `compare` |
| `read` | `read_variable` |
| `write` | `write_variable` |
| `test` | `cicd` |

## Timeouts

Always set explicit `--timeout` in scripts.

| Operation | Typical timeout |
| --- | --- |
| `ping`, `status`, `app-state`, `permissions` | 5-10s |
| `read`, `write`, `start`, `stop`, `disconnect` | 15-30s |
| `connect`, `compare`, `export` | 30-60s |
| `import`, `build`, `download`, `test`, snapshots | 120s |

## Error Handling

Successful commands print JSON data to `stdout`.

Failed commands print human-readable diagnostics to `stderr` and should exit
non-zero.

Common failures:

| Error | Meaning | Fix |
| --- | --- | --- |
| `Reverse pipe error: Timeout...` | Daemon is not running, busy, or blocked by a CODESYS dialog. | Check CODESYS and retry with a larger timeout. |
| `Not connected. Call connect_to_device first.` | Command needs an online PLC session. | Run `connect`. |
| `Forbidden by daemon settings` | Permission-gated command is blocked. | Change settings in the daemon dashboard. |
| `Invalid expression` | Variable is not exported to the online application. | Check symbol path/export settings. |
| `IMPORT.xml was not generated` | Disk state could not be converted into an import patch. | Run `compare`, inspect `.dump/compare_report.json`, then fix project-view. |

## Shell Notes

Use Windows Python when calling from WSL:

```bash
python.exe cli/cds_text_sync.py status --timeout 10
```

If the installed command is not found, use the source form:

```bash
python cli/cds_text_sync.py status --timeout 10
```
