---
name: cds-text-sync
description: Operate the CODESYS text sync CLI (`cts`) safely across an exported project folder, the CODESYS IDE daemon, and a PLC. Use for `cts` command selection, folder/IDE synchronization, builds and downloads, PLC lifecycle or variable access, offline engine operations, and troubleshooting cds-text-sync workflows.
disable-model-invocation: true
---

# Operate CODESYS Text Sync

Treat the exported project folder as the source of truth unless the user explicitly requests recovery or export from the IDE.

## Preserve the State Model

Keep the three states distinct:

```text
folder --import--> CODESYS IDE --download--> PLC
folder <--export-- CODESYS IDE
```

- Deploy production changes only from folder to IDE to PLC.
- Use `cts export` to bootstrap or intentionally refresh the folder from the IDE. Warn that it can replace projected files.
- Do not assume a successful import changed the PLC. Build and download are separate operations.
- Do not assume `ping` or `status` connects to the PLC.

## Inspect Before Acting

1. Resolve the project root and confirm whether `project-view/` exists.
2. Run `cts --help` when command availability matters.
3. Run `cts <command> --help` before using unfamiliar or version-sensitive options.
4. Run `cts status` or `cts ping` when daemon, IDE, or PLC state affects the task.
5. Prefer JSON output for parsing and `--pretty` for user-facing inspection.

Read [references/commands.md](references/commands.md) when selecting commands or diagnosing a workflow. Treat installed CLI help as authoritative if it differs from the reference.

## Apply Folder Changes

Use this sequence for normal source changes:

1. Edit files under `project-view/`.
2. Run `cts compare`.
3. Run `cts import --dry-run`.
4. Disconnect before import with `cts disconnect` when the IDE is online with the PLC.
5. Run `cts import`.
6. Run `cts build`.
7. Inspect build output and stop on errors.
8. Connect only when needed with `cts connect`.
9. Run `cts download` only when the user requested deployment to the PLC.
10. Verify application state after deployment.

There is no flag to import while the IDE is online. If the import preflight reports an online application, disconnect; if that does not clear it, end the online session in the CODESYS IDE before retrying.

## Control Mutation Scope

Classify commands before running them:

- Read-only: help, ping, status, compare, project inspection, log reads, variable reads, and dry runs.
- Folder-writing: export and offline projection generation.
- IDE-writing: import, POU updates, and POU deletion.
- PLC-affecting: connect, disconnect, download, start, stop, variable writes, and restore with apply.

Read-only diagnostics are safe defaults. Require a clear user request before exporting over files, deleting objects, downloading to a PLC, writing variables, restoring values, or changing PLC run state.

For variable writes, state that the PLC program may overwrite the value on the next scan. Prefer snapshots before broad restores and preserve dry-run behavior until application is explicitly requested.

## Diagnose Failures

- If the CLI is unavailable, report the missing executable and inspect project documentation for the expected environment.
- If the daemon is unreachable, verify that `Project_daemon.py` is running inside CODESYS before changing project files.
- If import is rejected while online, disconnect and retry the dry run. There is no override; when disconnect does not clear the online state, report that the online session must be closed in the CODESYS IDE.
- If a command or daemon method is unknown, compare `cts --help`, subcommand help, and daemon version. Do not assume every CLI-exposed method is implemented by the active daemon.
- If build or download fails, read the IDE log and report the exact errors without proceeding to later mutation steps.
- If folder and IDE state disagree unexpectedly, use compare and project inspection first. Do not resolve the discrepancy with export or import until the intended source of truth is established.

## Report Results

Report:

- project root and detected state,
- commands run,
- folder, IDE, and PLC changes separately,
- build result,
- application state when queried,
- any skipped deployment or unresolved version mismatch.

Do not claim the PLC is updated merely because folder import or build succeeded.
