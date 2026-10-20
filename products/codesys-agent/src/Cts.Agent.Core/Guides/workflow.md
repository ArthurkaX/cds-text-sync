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
- Read the `[INFO]` lines a command prints before its answer. `cts compare` reads both sides against the sync base. An IDE-only change is reported as `ide_changed`; it stays in the IDE until `cts export` or `cts sync` is chosen. Commands can also report what someone changed in the IDE outside cts since the previous command.

## Inspect Before Acting

1. Resolve the project root and confirm whether `project-view/` exists.
2. Run `cts guide` for the guides that ship with this CLI version — this
   `workflow` guide, the `commands` reference, and `visu-svg` authoring.
3. Run `cts --help` when command availability matters, and
   `cts <command> --help` before using unfamiliar or version-sensitive options.
4. Run `cts status` when IDE or PLC state affects the task.
5. Read the first line of any command's output: it is the verdict (`ok compare
   unchanged=26 modified=0`), and it is all you usually need. Add `--json` when
   a script needs the whole payload, `--pretty` for a human reading a terminal.

Run `cts guide commands` when selecting commands or diagnosing a workflow. Treat installed CLI help as authoritative if it differs from the guide.

## Reading the context

The last line of a command's answer names where it ran: `ide-3684 · Demo`,
the IDE (the value `--target` takes) and its open project; `--json` carries
the same as `instance`. `cts status` adds the PLC state and whether edits are
allowed: `ok status ide=ide-3684 plc=offline edits=allowed unsaved=false`.
`edits=blocked` means the IDE is online with the PLC: run `cts disconnect`,
then repeat the command; do not edit online. A state cts cannot read
(`plc=unknown`, no `edits=`) is not permission: an edit is refused then, so
ask before editing.

## Apply Folder Changes

### Change a program on a running PLC

```text
cts disconnect
cts sync --save
cts build
cts download
cts write ... (restart the logic if needed)
```

Use this sequence for normal source changes:

1. Run `cts compare` first. An `ide_changed` object was edited in the IDE since the last sync, and its file does not hold that edit yet: run `cts sync` so it does (an object both sides changed is merged), then edit the file. This is also how to fix something that is wrong only in the IDE: `cts sync`, correct the file, `cts import`. When the IDE's edits are the fault and none of them is to be kept, `cts import --force` gives the IDE the files' text instead; it overwrites every `ide_changed` object, their IDE text kept on `refs/cts/overwritten`.
2. Edit files under `project-view/`, then run `cts compare` again — it lists only what differs, so it is short by design; `--all` if you need the unchanged objects and the contents.
3. Run `cts import --dry-run`.
4. Disconnect before import with `cts disconnect` when the IDE is online with the PLC.
5. Run `cts import`.
6. Run `cts build`.
7. Inspect build output and stop on errors.
8. Connect only when needed with `cts connect`.
9. Run `cts download` only when the user requested deployment to the PLC.
10. Verify application state after deployment — do not read variables, or report
    the deployment as working, just because the download returned. `cts
    download` waits for the application to be running before it returns
    (`ready`, `ready_after_s`); when the login was done by hand in the IDE, run
    `cts wait-ready [--var NAME]` first. A download that never became ready
    exits non-zero and says why.

There is no flag to edit the project while the IDE is online. The refusal covers every project edit: import, deletion, `set-sync-folder`, and simulation mode. It answers *"The IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat `cts import`."* — the message names the command to repeat (`cts import`, `cts set-sync-folder`, `cts project simulate on`). If disconnecting does not clear it, end the online session in the CODESYS IDE before retrying. An edit applied online leaves the new objects half-applied: their symbols are never exported to the running application, so later reads fail with *"is not exported to the online application"* even after a full download.

`cts import` applies to the in-memory project and does **not** save it: saving also commits whatever else is open in the IDE, so it stays the user's decision. The response carries an `unsaved` warning — pass it on, and tell the user the import is lost if the project is closed or reloaded before they save. Use `--save` only when the user asked for it.

`cts import` then moves the sync base `refs/cts/base` for the files it carried, so a second `cts compare` comes back clean. A file holding an object that did not reach the IDE, or a conflict, keeps its old base, so the disk copy of that edit survives and the next import tries it again.

Deleting all of an object's files deletes the object in the IDE, unless the project denies it (`delete_pou` in `cts permissions`). A text object the IDE has that was never in `project-view/` is left alone by `cts import`; `cts import --force` deletes it (its text kept on `refs/cts/overwritten`), or delete it in the IDE.

## Keep the Work in Git

The sync folder is a git repository and the IDE project is a working copy of its checked-out branch. Use cts for git work that touches the project, so the IDE and the files stay one state:

- `cts commit -m MSG` syncs the IDE and the folder, then commits the branch. It never commits a `*.project`; only the project's owner adds `--publish` to put the project file in the repository.
- `cts push` sends the branch to the team's repository. A refusal that the remote has commits the branch lacks means pull first.
- `cts project update` pulls the team's commits and imports them into the IDE (on a colleague's machine onto the published project file). When git stops at a conflict, a person resolves it in their git program (`cts open`) and commits the merge; `cts project update` then imports it.
- `cts branch [NAME]` lists branches or creates one at the current commit; `cts checkout TARGET` switches and carries the difference into the IDE; `cts log` lists commits to go back to.
- `cts compare --tool --against REF` shows a person the IDE against a branch, tag or commit.

Checkout and project update refuse while the IDE is online, and checkout also until `cts compare` is clean; each refusal names the command that gets there. Push only when the user asked for it. `cts guide commands` has the details.

## Control Mutation Scope

Classify commands before running them:

- Read-only: help, ping, status, compare, project inspection, `cts fmt` without `--write`, `cts fsm`, `cts log`, log reads, variable reads, and dry runs.
- Folder-writing: export, offline projection generation, and git commits (`cts commit`, `cts branch NAME`).
- IDE-writing: import, sync, checkout, project update, `cts fmt --write`, object deletion, sync-folder changes, and simulation mode. All are refused while the IDE is online with the PLC — disconnect first.
- Team-affecting: `cts push`, and `cts commit --publish` once pushed.
- PLC-affecting: connect, disconnect, download, start, stop, variable writes, and restore with apply.

Read-only diagnostics are safe defaults. Require a clear user request before exporting over files, deleting objects, downloading to a PLC, writing variables, restoring values, or changing PLC run state.

For variable writes, state that the PLC program may overwrite the value on the next scan. Prefer snapshots before broad restores and preserve dry-run behavior until application is explicitly requested.

## Diagnose Failures

- If the CLI is unavailable, report the missing executable and inspect project documentation for the expected environment.
- If no in-IDE agent answers, start it before changing project files: `cts project open --path <project> --launch`, or ask the user to run cds-text-sync in CODESYS (Tools > Scripting > Scripts > C > cds-text-sync).
- If import is rejected while online, disconnect and retry the dry run. There is no override; when disconnect does not clear the online state, report that the online session must be closed in the CODESYS IDE.
- If a command or method is unknown, compare `cts --help`, subcommand help, and the agent's build in `cts agent list`. A `[WARN]` that the IDE's agent is another build than `cts` means the two installs differ: ask the user to close CODESYS, run `cts install`, and start it again.
- If `cts connect --ip` finds no PLC, read its reason (this PC does not reach the address, or no runtime answers there); `cts scan` lists the PLCs the gateway finds, with the IP to connect to.
- If the build reports that the device description is missing, or sync refuses a device of another version, `cts project device-types` lists the installed ones and `cts project change-device` switches the device to one of them (the IDE's Update Device).
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
